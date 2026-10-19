import Cocoa
import CryptoKit
import Darwin
import FlutterMacOS
import Security

struct BackendConfiguration: Equatable {
  let host: String
  let port: UInt16
  let instanceToken: String

  var channelValue: [String: Any] {
    [
      "host": host,
      "port": Int(port),
      "instanceToken": instanceToken,
    ]
  }
}

enum BackendLifecycleError: LocalizedError {
  case missingResource(String)
  case noAvailablePort
  case tokenGenerationFailed
  case processLaunchFailed(String)
  case processExited(Int32)
  case identityMismatch
  case startupTimedOut

  var errorDescription: String? {
    switch self {
    case .missingResource(let path):
      return "LogosGo 安裝不完整，缺少必要資源：\(path)"
    case .noAvailablePort:
      return "無法取得本機連線埠，請稍後重試。"
    case .tokenGenerationFailed:
      return "無法建立安全的本機連線識別。"
    case .processLaunchFailed(let detail):
      return "LogosGo 後端無法啟動：\(detail)"
    case .processExited(let status):
      return "LogosGo 後端在啟動期間停止（狀態碼 \(status)）。"
    case .identityMismatch:
      return "本機後端身分驗證失敗，請重新啟動 LogosGo。"
    case .startupTimedOut:
      return "LogosGo 後端啟動逾時，請重新啟動 App；若持續發生，請查看後端紀錄。"
    }
  }
}

final class BackendProcessController {
  static let serviceIdentity = "LogosGoBackend"
  static let startupTimeout: TimeInterval = 60
  static let pollInterval: TimeInterval = 0.25
  static let maximumLaunchAttempts = 3

  private let queue = DispatchQueue(label: "com.logosgo.desktop.backend-lifecycle")
  private var process: Process?
  private var logHandle: FileHandle?
  private var configuration: BackendConfiguration?
  private var waiters: [(Result<BackendConfiguration, Error>) -> Void] = []
  private var isStarting = false
  private var isStopping = false
  private var generation = 0

  func requestConfiguration(
    completion: @escaping (Result<BackendConfiguration, Error>) -> Void
  ) {
    queue.async {
      if let configuration = self.configuration {
        DispatchQueue.main.async { completion(.success(configuration)) }
        return
      }
      self.waiters.append(completion)
      guard !self.isStarting else { return }
      self.isStarting = true
      self.isStopping = false
      self.generation += 1
      self.launch(attempt: 1, generation: self.generation)
    }
  }

  func stop() {
    queue.sync {
      guard !self.isStopping else { return }
      self.isStopping = true
      self.generation += 1
      self.configuration = nil
      self.isStarting = false
      self.waiters.removeAll()
      self.stopProcess(gracePeriod: 3)
    }
  }

  private func launch(attempt: Int, generation: Int) {
    guard !isStopping, generation == self.generation else { return }

    #if DEBUG
    guard let paths = try? bundledPaths() else {
      finish(
        .success(
          BackendConfiguration(host: "127.0.0.1", port: 5001, instanceToken: "")
        ),
        generation: generation
      )
      return
    }
    #else
    let paths: (backend: URL, resourceRoot: URL, kataGo: URL)
    do {
      paths = try bundledPaths()
    } catch {
      finish(.failure(error), generation: generation)
      return
    }
    #endif

    guard let port = Self.allocateLoopbackPort() else {
      finish(.failure(BackendLifecycleError.noAvailablePort), generation: generation)
      return
    }
    guard let token = Self.makeInstanceToken() else {
      finish(.failure(BackendLifecycleError.tokenGenerationFailed), generation: generation)
      return
    }

    let configuration = BackendConfiguration(
      host: "127.0.0.1",
      port: port,
      instanceToken: token
    )
    let child = Process()
    child.executableURL = paths.backend
    child.arguments = [
      "--port", String(port),
      "--resource-root", paths.resourceRoot.path,
      "--katago-executable", paths.kataGo.path,
      "--parent-pid", String(getpid()),
    ]
    var environment = childEnvironment()
    environment["LOGOSGO_INSTANCE_TOKEN"] = token
    child.environment = environment

    do {
      let handle = try makeLogHandle()
      logHandle = handle
      child.standardOutput = handle
      child.standardError = handle
      child.currentDirectoryURL = handleLogDirectory()
      child.terminationHandler = { [weak self] terminated in
        guard let self else { return }
        self.queue.async {
          guard generation == self.generation, self.isStarting, !self.isStopping else { return }
          self.stopProcess(gracePeriod: 0)
          if attempt < Self.maximumLaunchAttempts {
            self.launch(attempt: attempt + 1, generation: generation)
          } else {
            self.finish(
              .failure(BackendLifecycleError.processExited(terminated.terminationStatus)),
              generation: generation
            )
          }
        }
      }
      try child.run()
      process = child
      pollHealth(
        configuration: configuration,
        deadline: Date().addingTimeInterval(Self.startupTimeout),
        generation: generation
      )
    } catch {
      stopProcess(gracePeriod: 0)
      if attempt < Self.maximumLaunchAttempts {
        launch(attempt: attempt + 1, generation: generation)
      } else {
        finish(
          .failure(BackendLifecycleError.processLaunchFailed(error.localizedDescription)),
          generation: generation
        )
      }
    }
  }

  private func bundledPaths() throws -> (backend: URL, resourceRoot: URL, kataGo: URL) {
    guard let resources = Bundle.main.resourceURL else {
      throw BackendLifecycleError.missingResource("Contents/Resources")
    }
    let root = resources.appendingPathComponent("LogosGoRuntime", isDirectory: true)
    let backend = root.appendingPathComponent("backend/logosgo-backend")
    let kataGo = root.appendingPathComponent("katago/katago")
    for resource in [root, backend, kataGo] where !FileManager.default.fileExists(atPath: resource.path) {
      throw BackendLifecycleError.missingResource(resource.lastPathComponent)
    }
    return (backend, root, kataGo)
  }

  private func childEnvironment() -> [String: String] {
    var environment: [String: String] = [
      "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
      "LANG": "en_US.UTF-8",
    ]
    for key in ["HOME", "TMPDIR"] {
      if let value = ProcessInfo.processInfo.environment[key] {
        environment[key] = value
      }
    }
    return environment
  }

  private func handleLogDirectory() -> URL {
    let base = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
    return base.appendingPathComponent("Logs/LogosGo", isDirectory: true)
  }

  private func makeLogHandle() throws -> FileHandle {
    let directory = handleLogDirectory()
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let file = directory.appendingPathComponent("backend.log")
    if !FileManager.default.fileExists(atPath: file.path) {
      FileManager.default.createFile(atPath: file.path, contents: nil)
    }
    let handle = try FileHandle(forWritingTo: file)
    try handle.seekToEnd()
    return handle
  }

  private func pollHealth(
    configuration: BackendConfiguration,
    deadline: Date,
    generation: Int
  ) {
    guard generation == self.generation, isStarting, !isStopping else { return }
    guard let process, process.isRunning else { return }
    guard Date() < deadline else {
      stopProcess(gracePeriod: 1)
      finish(.failure(BackendLifecycleError.startupTimedOut), generation: generation)
      return
    }

    var request = URLRequest(
      url: URL(string: "http://127.0.0.1:\(configuration.port)/health")!
    )
    request.timeoutInterval = 1
    request.setValue(configuration.instanceToken, forHTTPHeaderField: "X-LogosGo-Instance")
    let sessionConfiguration = URLSessionConfiguration.ephemeral
    sessionConfiguration.timeoutIntervalForRequest = 1
    let session = URLSession(configuration: sessionConfiguration)
    session.dataTask(with: request) { [weak self] data, response, _ in
      session.finishTasksAndInvalidate()
      guard let self else { return }
      self.queue.async {
        guard generation == self.generation, self.isStarting, !self.isStopping else { return }
        if let http = response as? HTTPURLResponse,
          http.statusCode == 200,
          let data,
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        {
          let expectedID = Self.instanceID(for: configuration.instanceToken)
          let matches = json["service"] as? String == Self.serviceIdentity
            && json["ready"] as? Bool == true
            && json["token_verified"] as? Bool == true
            && json["instance_id"] as? String == expectedID
          if matches {
            self.finish(.success(configuration), generation: generation)
          } else {
            self.stopProcess(gracePeriod: 1)
            self.finish(.failure(BackendLifecycleError.identityMismatch), generation: generation)
          }
          return
        }
        self.queue.asyncAfter(deadline: .now() + Self.pollInterval) {
          self.pollHealth(
            configuration: configuration,
            deadline: deadline,
            generation: generation
          )
        }
      }
    }.resume()
  }

  private func finish(
    _ result: Result<BackendConfiguration, Error>,
    generation: Int
  ) {
    guard generation == self.generation, isStarting, !isStopping else { return }
    isStarting = false
    if case .success(let value) = result {
      configuration = value
    }
    let completions = waiters
    waiters.removeAll()
    DispatchQueue.main.async {
      completions.forEach { $0(result) }
    }
  }

  private func stopProcess(gracePeriod: TimeInterval) {
    guard let child = process else {
      closeLogHandle()
      return
    }
    process = nil
    child.terminationHandler = nil
    if child.isRunning {
      child.terminate()
      let limit = Date().addingTimeInterval(gracePeriod)
      while child.isRunning, Date() < limit {
        Thread.sleep(forTimeInterval: 0.05)
      }
      if child.isRunning {
        Darwin.kill(-child.processIdentifier, SIGKILL)
        Darwin.kill(child.processIdentifier, SIGKILL)
      }
    }
    closeLogHandle()
  }

  private func closeLogHandle() {
    try? logHandle?.synchronize()
    try? logHandle?.close()
    logHandle = nil
  }

  static func makeInstanceToken() -> String? {
    var bytes = [UInt8](repeating: 0, count: 32)
    guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
      return nil
    }
    return Data(bytes).base64EncodedString()
      .replacingOccurrences(of: "+", with: "-")
      .replacingOccurrences(of: "/", with: "_")
      .replacingOccurrences(of: "=", with: "")
  }

  static func instanceID(for token: String) -> String {
    SHA256.hash(data: Data(token.utf8)).map { String(format: "%02x", $0) }.joined().prefix(24)
      .description
  }

  static func allocateLoopbackPort() -> UInt16? {
    let descriptor = socket(AF_INET, SOCK_STREAM, 0)
    guard descriptor >= 0 else { return nil }
    defer { Darwin.close(descriptor) }
    var address = sockaddr_in()
    address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    address.sin_family = sa_family_t(AF_INET)
    address.sin_port = 0
    address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
    let bound = withUnsafePointer(to: &address) { pointer in
      pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
        Darwin.bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
      }
    }
    guard bound == 0 else { return nil }
    var length = socklen_t(MemoryLayout<sockaddr_in>.size)
    let named = withUnsafeMutablePointer(to: &address) { pointer in
      pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
        getsockname(descriptor, $0, &length)
      }
    }
    guard named == 0 else { return nil }
    return UInt16(bigEndian: address.sin_port)
  }
}

@main
class AppDelegate: FlutterAppDelegate {
  let backendController = BackendProcessController()

  override func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
    return true
  }

  override func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
    return true
  }

  override func applicationWillTerminate(_ notification: Notification) {
    backendController.stop()
  }
}
