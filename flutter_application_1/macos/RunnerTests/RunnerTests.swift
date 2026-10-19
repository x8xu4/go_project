import Cocoa
import FlutterMacOS
import XCTest
@testable import LogosGo

class RunnerTests: XCTestCase {
  func testBackendConfigurationChannelValue() {
    let value = BackendConfiguration(
      host: "127.0.0.1",
      port: 53123,
      instanceToken: "test-token"
    ).channelValue

    XCTAssertEqual(value["host"] as? String, "127.0.0.1")
    XCTAssertEqual(value["port"] as? Int, 53123)
    XCTAssertEqual(value["instanceToken"] as? String, "test-token")
  }

  func testInstanceTokensAreRandomAndURLSafe() {
    let first = BackendProcessController.makeInstanceToken()
    let second = BackendProcessController.makeInstanceToken()

    XCTAssertNotNil(first)
    XCTAssertNotNil(second)
    XCTAssertNotEqual(first, second)
    XCTAssertFalse(first?.contains("=") ?? true)
    XCTAssertFalse(first?.contains("+") ?? true)
    XCTAssertFalse(first?.contains("/") ?? true)
  }

  func testInstanceIDMatchesBackendHashContract() {
    XCTAssertEqual(
      BackendProcessController.instanceID(for: "private-runner-token"),
      "616b8e80ea9bb49a45969f54"
    )
  }

  func testDynamicLoopbackPortIsValid() {
    let port = BackendProcessController.allocateLoopbackPort()
    XCTAssertNotNil(port)
    XCTAssertGreaterThan(port ?? 0, 0)
  }

  func testApplicationTerminationStopsSafelyWithoutBackendProcess() {
    let delegate = AppDelegate()
    delegate.applicationWillTerminate(
      Notification(name: NSApplication.willTerminateNotification)
    )
  }
}
