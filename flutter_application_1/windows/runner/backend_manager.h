#ifndef RUNNER_BACKEND_MANAGER_H_
#define RUNNER_BACKEND_MANAGER_H_

#include <windows.h>

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

struct BackendConfiguration {
  std::string host;
  uint16_t port = 0;
  std::string instance_token;
  std::string instance_id;
};

// Owns the packaged LogosGo backend and every process that it creates.
//
// Startup is deliberately bounded and does not expose a configuration until
// the authenticated health endpoint proves that the expected backend is ready.
// The Job Object is the abnormal-exit safety net; normal shutdown first uses
// the backend's authenticated /shutdown endpoint.
class BackendManager {
 public:
  BackendManager();
  ~BackendManager();

  BackendManager(const BackendManager&) = delete;
  BackendManager& operator=(const BackendManager&) = delete;

  bool Start(std::wstring* error_message);
  void Stop();

  bool is_ready() const { return ready_; }
  const BackendConfiguration& configuration() const { return configuration_; }

 private:
  struct RuntimeLayout {
    std::filesystem::path runtime_root;
    std::filesystem::path backend_executable;
    std::filesystem::path opencl_executable;
    std::filesystem::path eigen_executable;
    std::filesystem::path model_file;
    std::filesystem::path config_file;
    std::filesystem::path corpus_file;
  };

  struct ProbeResult {
    bool ready = false;
    std::wstring detail;
    std::filesystem::path log_file;
  };

  bool ResolveRuntimeLayout(RuntimeLayout* layout,
                            std::wstring* error_message);
  bool InitializeWritablePaths(std::wstring* error_message);
  bool InitializeJob(std::wstring* error_message);
  bool InitializeWinsock(std::wstring* error_message);
  bool GenerateInstanceToken(std::wstring* error_message);
  bool SelectKataGo(const RuntimeLayout& layout,
                    std::filesystem::path* selected,
                    std::wstring* error_message);
  ProbeResult ProbeKataGo(const std::wstring& backend_name,
                          const std::filesystem::path& executable,
                          const RuntimeLayout& layout);
  bool AllocateLoopbackPort(uint16_t* port, std::wstring* error_message);
  bool LaunchBackend(const RuntimeLayout& layout,
                     const std::filesystem::path& katago_executable,
                     uint16_t port,
                     int attempt,
                     std::wstring* error_message);
  bool PollHealth(uint16_t port,
                  std::string* instance_id,
                  std::wstring* error_message);
  bool SendShutdownRequest();
  bool HttpRequest(const wchar_t* method,
                   const wchar_t* path,
                   uint16_t port,
                   DWORD timeout_ms,
                   DWORD* status_code,
                   std::string* response_body);
  bool LaunchJobProcess(const std::filesystem::path& executable,
                        const std::vector<std::wstring>& arguments,
                        const std::filesystem::path& working_directory,
                        HANDLE output_handle,
                        PROCESS_INFORMATION* process,
                        std::wstring* error_message);
  HANDLE OpenUniqueLog(const std::wstring& prefix,
                       bool inheritable,
                       std::filesystem::path* path,
                       std::wstring* error_message);
  void Log(const std::wstring& message);
  void StopBackendProcess(bool terminate_job);
  void CloseRuntimeHandles();

  RuntimeLayout runtime_layout_;
  std::filesystem::path logs_directory_;
  std::filesystem::path runner_log_path_;
  std::filesystem::path backend_log_path_;
  std::filesystem::path selected_katago_;

  HANDLE runner_log_ = INVALID_HANDLE_VALUE;
  HANDLE job_ = nullptr;
  HANDLE backend_process_ = nullptr;
  bool winsock_initialized_ = false;
  bool ready_ = false;
  BackendConfiguration configuration_;
};

#endif  // RUNNER_BACKEND_MANAGER_H_
