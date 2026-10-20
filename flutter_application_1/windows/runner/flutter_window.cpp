#include "flutter_window.h"

#include <flutter/standard_method_codec.h>

#include <optional>
#include <string>

#include "flutter/generated_plugin_registrant.h"
#include "utils.h"

FlutterWindow::FlutterWindow(const flutter::DartProject& project,
                             BackendManager* backend_manager)
    : project_(project), backend_manager_(backend_manager) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());

  backend_channel_ = std::make_unique<
      flutter::MethodChannel<flutter::EncodableValue>>(
      flutter_controller_->engine()->messenger(), "logosgo/backend",
      &flutter::StandardMethodCodec::GetInstance());
  backend_channel_->SetMethodCallHandler(
      [this](const flutter::MethodCall<flutter::EncodableValue>& call,
             std::unique_ptr<
                 flutter::MethodResult<flutter::EncodableValue>> result) {
        if (call.method_name() != "getBackendConfiguration") {
          result->NotImplemented();
          return;
        }
        if (backend_manager_ == nullptr) {
          result->Error("BACKEND_STARTUP_FAILED",
                        "Windows backend manager is unavailable.");
          return;
        }

        std::wstring error;
        if (!backend_manager_->Start(&error)) {
          result->Error("BACKEND_STARTUP_FAILED",
                        Utf8FromUtf16(error.c_str()));
          return;
        }

        const BackendConfiguration& configuration =
            backend_manager_->configuration();
        flutter::EncodableMap value = {
            {flutter::EncodableValue("host"),
             flutter::EncodableValue(configuration.host)},
            {flutter::EncodableValue("port"),
             flutter::EncodableValue(
                 static_cast<int32_t>(configuration.port))},
            {flutter::EncodableValue("instanceToken"),
             flutter::EncodableValue(configuration.instance_token)},
        };
        result->Success(flutter::EncodableValue(value));
      });
  SetChildContent(flutter_controller_->view()->GetNativeWindow());

  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    this->Show();
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();

  return true;
}

void FlutterWindow::OnDestroy() {
  backend_channel_.reset();
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_FONTCHANGE:
      flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}
