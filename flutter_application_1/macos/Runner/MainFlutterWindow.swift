import Cocoa
import FlutterMacOS

class MainFlutterWindow: NSWindow {
  private var backendChannel: FlutterMethodChannel?

  override func awakeFromNib() {
    let flutterViewController = FlutterViewController()
    let windowFrame = self.frame
    self.contentViewController = flutterViewController
    self.setFrame(windowFrame, display: true)

    RegisterGeneratedPlugins(registry: flutterViewController)

    let channel = FlutterMethodChannel(
      name: "logosgo/backend",
      binaryMessenger: flutterViewController.engine.binaryMessenger
    )
    channel.setMethodCallHandler { call, result in
      guard call.method == "getBackendConfiguration" else {
        result(FlutterMethodNotImplemented)
        return
      }
      guard let delegate = NSApplication.shared.delegate as? AppDelegate else {
        result(
          FlutterError(
            code: "backend_lifecycle_unavailable",
            message: "LogosGo 無法存取本機後端管理器。",
            details: nil
          )
        )
        return
      }
      delegate.backendController.requestConfiguration { configuration in
        switch configuration {
        case .success(let value):
          result(value.channelValue)
        case .failure(let error):
          result(
            FlutterError(
              code: "backend_start_failed",
              message: error.localizedDescription,
              details: nil
            )
          )
        }
      }
    }
    backendChannel = channel

    super.awakeFromNib()
  }
}
