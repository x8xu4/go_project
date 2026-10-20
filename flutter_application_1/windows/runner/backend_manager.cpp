#include <winsock2.h>
#include <ws2tcpip.h>

#include "backend_manager.h"

#include <bcrypt.h>
#include <winhttp.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cwchar>
#include <filesystem>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

namespace {

constexpr wchar_t kHealthPath[] = L"/health";
constexpr wchar_t kShutdownPath[] = L"/shutdown";
constexpr wchar_t kInstanceHeader[] = L"X-LogosGo-Instance";
constexpr char kKataGoReadyMarker[] =
    "Started, ready to begin handling requests";
constexpr DWORD kProbeTimeoutMs = 120000;
constexpr DWORD kHealthTimeoutMs = 60000;
constexpr DWORD kShutdownTimeoutMs = 5000;
constexpr int kMaximumLaunchAttempts = 3;
constexpr size_t kMaximumDiagnosticBytes = 2 * 1024 * 1024;

bool IsValidHandle(HANDLE handle) {
  return handle != nullptr && handle != INVALID_HANDLE_VALUE;
}

std::wstring WindowsError(DWORD error_code) {
  wchar_t* message = nullptr;
  const DWORD length = ::FormatMessageW(
      FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
          FORMAT_MESSAGE_IGNORE_INSERTS,
      nullptr, error_code, 0, reinterpret_cast<wchar_t*>(&message), 0,
      nullptr);
  if (length == 0 || message == nullptr) {
    return L"Windows error " + std::to_wstring(error_code);
  }
  std::wstring result(message, length);
  ::LocalFree(message);
  while (!result.empty() &&
         (result.back() == L'\r' || result.back() == L'\n' ||
          result.back() == L' ')) {
    result.pop_back();
  }
  return result;
}

std::string Utf8FromWide(const std::wstring& value) {
  if (value.empty()) {
    return std::string();
  }
  const int size = ::WideCharToMultiByte(
      CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
      static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
  if (size <= 0) {
    return std::string();
  }
  std::string output(static_cast<size_t>(size), '\0');
  const int converted = ::WideCharToMultiByte(
      CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
      static_cast<int>(value.size()), output.data(), size, nullptr, nullptr);
  return converted == size ? output : std::string();
}

std::wstring WideFromUtf8(const std::string& value) {
  if (value.empty()) {
    return std::wstring();
  }
  const int size = ::MultiByteToWideChar(
      CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
      static_cast<int>(value.size()), nullptr, 0);
  if (size <= 0) {
    return std::wstring();
  }
  std::wstring output(static_cast<size_t>(size), L'\0');
  const int converted = ::MultiByteToWideChar(
      CP_UTF8, MB_ERR_INVALID_CHARS, value.data(),
      static_cast<int>(value.size()), output.data(), size);
  return converted == size ? output : std::wstring();
}

std::wstring QuoteCommandLineArgument(const std::wstring& argument) {
  if (argument.empty()) {
    return L"\"\"";
  }
  if (argument.find_first_of(L" \t\n\v\"") == std::wstring::npos) {
    return argument;
  }

  std::wstring quoted = L"\"";
  size_t backslashes = 0;
  for (const wchar_t character : argument) {
    if (character == L'\\') {
      ++backslashes;
      continue;
    }
    if (character == L'\"') {
      quoted.append(backslashes * 2 + 1, L'\\');
      quoted.push_back(L'\"');
      backslashes = 0;
      continue;
    }
    quoted.append(backslashes, L'\\');
    backslashes = 0;
    quoted.push_back(character);
  }
  quoted.append(backslashes * 2, L'\\');
  quoted.push_back(L'\"');
  return quoted;
}

std::wstring BuildCommandLine(
    const std::filesystem::path& executable,
    const std::vector<std::wstring>& arguments) {
  std::wstring command = QuoteCommandLineArgument(executable.wstring());
  for (const std::wstring& argument : arguments) {
    command.push_back(L' ');
    command.append(QuoteCommandLineArgument(argument));
  }
  return command;
}

bool IsRegularFile(const std::filesystem::path& path) {
  std::error_code error;
  return std::filesystem::is_regular_file(path, error) && !error;
}

bool ReadEnvironmentVariable(const wchar_t* name, std::wstring* value) {
  const DWORD required = ::GetEnvironmentVariableW(name, nullptr, 0);
  if (required == 0) {
    return false;
  }
  std::vector<wchar_t> buffer(static_cast<size_t>(required));
  const DWORD written =
      ::GetEnvironmentVariableW(name, buffer.data(), required);
  if (written == 0 || written >= required) {
    return false;
  }
  value->assign(buffer.data(), written);
  return true;
}

bool ExecutableDirectory(std::filesystem::path* directory,
                         std::wstring* error_message) {
  std::vector<wchar_t> buffer(32768, L'\0');
  const DWORD length = ::GetModuleFileNameW(
      nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
  if (length == 0 || length >= buffer.size()) {
    *error_message = L"Cannot resolve the LogosGo executable path: " +
                     WindowsError(::GetLastError());
    return false;
  }
  *directory = std::filesystem::path(
                   std::wstring(buffer.data(), static_cast<size_t>(length)))
                   .parent_path();
  return true;
}

std::wstring TimestampForFileName() {
  SYSTEMTIME value{};
  ::GetLocalTime(&value);
  wchar_t buffer[64]{};
  swprintf_s(
      buffer, L"%04u%02u%02u-%02u%02u%02u-%lu",
      static_cast<unsigned int>(value.wYear),
      static_cast<unsigned int>(value.wMonth),
      static_cast<unsigned int>(value.wDay),
      static_cast<unsigned int>(value.wHour),
      static_cast<unsigned int>(value.wMinute),
      static_cast<unsigned int>(value.wSecond),
      static_cast<unsigned long>(::GetCurrentProcessId()));
  return buffer;
}

std::wstring TimestampForLogLine() {
  SYSTEMTIME value{};
  ::GetLocalTime(&value);
  wchar_t buffer[64]{};
  swprintf_s(
      buffer, L"%04u-%02u-%02u %02u:%02u:%02u.%03u",
      static_cast<unsigned int>(value.wYear),
      static_cast<unsigned int>(value.wMonth),
      static_cast<unsigned int>(value.wDay),
      static_cast<unsigned int>(value.wHour),
      static_cast<unsigned int>(value.wMinute),
      static_cast<unsigned int>(value.wSecond),
      static_cast<unsigned int>(value.wMilliseconds));
  return buffer;
}

std::string Base64UrlEncode(const uint8_t* bytes, size_t length) {
  static constexpr char kAlphabet[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
  std::string output;
  output.reserve((length * 4 + 2) / 3);
  size_t index = 0;
  while (index + 3 <= length) {
    const uint32_t value = (static_cast<uint32_t>(bytes[index]) << 16) |
                           (static_cast<uint32_t>(bytes[index + 1]) << 8) |
                           static_cast<uint32_t>(bytes[index + 2]);
    output.push_back(kAlphabet[(value >> 18) & 0x3f]);
    output.push_back(kAlphabet[(value >> 12) & 0x3f]);
    output.push_back(kAlphabet[(value >> 6) & 0x3f]);
    output.push_back(kAlphabet[value & 0x3f]);
    index += 3;
  }
  const size_t remaining = length - index;
  if (remaining == 1) {
    const uint32_t value = static_cast<uint32_t>(bytes[index]) << 16;
    output.push_back(kAlphabet[(value >> 18) & 0x3f]);
    output.push_back(kAlphabet[(value >> 12) & 0x3f]);
  } else if (remaining == 2) {
    const uint32_t value = (static_cast<uint32_t>(bytes[index]) << 16) |
                           (static_cast<uint32_t>(bytes[index + 1]) << 8);
    output.push_back(kAlphabet[(value >> 18) & 0x3f]);
    output.push_back(kAlphabet[(value >> 12) & 0x3f]);
    output.push_back(kAlphabet[(value >> 6) & 0x3f]);
  }
  return output;
}

std::string InstanceIdForToken(const std::string& token) {
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash_handle = nullptr;
  DWORD object_size = 0;
  DWORD hash_size = 0;
  DWORD property_size = 0;
  std::vector<uint8_t> hash_object;
  std::vector<uint8_t> hash;

  NTSTATUS status = ::BCryptOpenAlgorithmProvider(
      &algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0);
  if (status == 0) {
    status = ::BCryptGetProperty(
        algorithm, BCRYPT_OBJECT_LENGTH,
        reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size),
        &property_size, 0);
  }
  if (status == 0) {
    status = ::BCryptGetProperty(
        algorithm, BCRYPT_HASH_LENGTH, reinterpret_cast<PUCHAR>(&hash_size),
        sizeof(hash_size), &property_size, 0);
  }
  if (status == 0 && object_size != 0 && hash_size != 0) {
    hash_object.resize(object_size);
    hash.resize(hash_size);
    status = ::BCryptCreateHash(
        algorithm, &hash_handle, hash_object.data(), object_size, nullptr, 0,
        0);
  }
  if (status == 0) {
    std::vector<uint8_t> token_bytes(token.begin(), token.end());
    status = ::BCryptHashData(
        hash_handle, token_bytes.data(),
        static_cast<ULONG>(token_bytes.size()), 0);
  }
  if (status == 0) {
    status = ::BCryptFinishHash(hash_handle, hash.data(), hash_size, 0);
  }

  if (hash_handle != nullptr) {
    ::BCryptDestroyHash(hash_handle);
  }
  if (algorithm != nullptr) {
    ::BCryptCloseAlgorithmProvider(algorithm, 0);
  }
  if (status != 0 || hash.size() < 12) {
    return std::string();
  }

  static constexpr char kHex[] = "0123456789abcdef";
  std::string instance_id;
  instance_id.reserve(24);
  for (size_t index = 0; index < 12; ++index) {
    instance_id.push_back(kHex[(hash[index] >> 4) & 0x0f]);
    instance_id.push_back(kHex[hash[index] & 0x0f]);
  }
  return instance_id;
}

std::string CompactJson(const std::string& input) {
  std::string output;
  output.reserve(input.size());
  for (const unsigned char character : input) {
    if (!std::isspace(character)) {
      output.push_back(static_cast<char>(character));
    }
  }
  return output;
}

bool JsonHasString(const std::string& json,
                   const std::string& key,
                   const std::string& expected) {
  return json.find("\"" + key + "\":\"" + expected + "\"") !=
         std::string::npos;
}

bool JsonHasBoolean(const std::string& json,
                    const std::string& key,
                    bool expected) {
  return json.find("\"" + key + "\":" +
                   (expected ? "true" : "false")) != std::string::npos;
}

bool JsonHasInteger(const std::string& json,
                    const std::string& key,
                    int expected) {
  return json.find("\"" + key + "\":" + std::to_string(expected)) !=
         std::string::npos;
}

bool JsonString(const std::string& json,
                const std::string& key,
                std::string* value) {
  const std::string prefix = "\"" + key + "\":\"";
  const size_t start = json.find(prefix);
  if (start == std::string::npos) {
    return false;
  }
  const size_t value_start = start + prefix.size();
  const size_t end = json.find('"', value_start);
  if (end == std::string::npos || end == value_start) {
    return false;
  }
  *value = json.substr(value_start, end - value_start);
  return true;
}

std::string ReadDiagnosticFile(const std::filesystem::path& path) {
  HANDLE file = ::CreateFileW(path.c_str(), GENERIC_READ,
                              FILE_SHARE_READ | FILE_SHARE_WRITE |
                                  FILE_SHARE_DELETE,
                              nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL,
                              nullptr);
  if (!IsValidHandle(file)) {
    return std::string();
  }

  LARGE_INTEGER size{};
  if (!::GetFileSizeEx(file, &size) || size.QuadPart <= 0) {
    ::CloseHandle(file);
    return std::string();
  }
  const LONGLONG bytes_to_read =
      std::min<LONGLONG>(size.QuadPart,
                         static_cast<LONGLONG>(kMaximumDiagnosticBytes));
  if (size.QuadPart > bytes_to_read) {
    LARGE_INTEGER offset{};
    offset.QuadPart = size.QuadPart - bytes_to_read;
    ::SetFilePointerEx(file, offset, nullptr, FILE_BEGIN);
  }

  std::string output(static_cast<size_t>(bytes_to_read), '\0');
  DWORD total = 0;
  while (total < output.size()) {
    DWORD read = 0;
    const DWORD remaining = static_cast<DWORD>(
        std::min<size_t>(output.size() - total, MAXDWORD));
    if (!::ReadFile(file, output.data() + total, remaining, &read, nullptr) ||
        read == 0) {
      break;
    }
    total += read;
  }
  ::CloseHandle(file);
  output.resize(total);
  return output;
}

}  // namespace

BackendManager::BackendManager() = default;

BackendManager::~BackendManager() {
  Stop();
}

bool BackendManager::Start(std::wstring* error_message) {
  if (ready_) {
    return true;
  }

  Stop();
  if (!InitializeWritablePaths(error_message) ||
      !ResolveRuntimeLayout(&runtime_layout_, error_message) ||
      !InitializeWinsock(error_message) || !InitializeJob(error_message) ||
      !GenerateInstanceToken(error_message)) {
    const std::wstring preserved = *error_message;
    Stop();
    *error_message = preserved;
    return false;
  }

  Log(L"Starting packaged Windows backend lifecycle");
  if (!SelectKataGo(runtime_layout_, &selected_katago_, error_message)) {
    const std::wstring preserved = *error_message;
    Stop();
    *error_message = preserved;
    return false;
  }

  for (int attempt = 1; attempt <= kMaximumLaunchAttempts; ++attempt) {
    uint16_t port = 0;
    std::wstring attempt_error;
    if (!AllocateLoopbackPort(&port, &attempt_error)) {
      Log(L"Port allocation failed: " + attempt_error);
      continue;
    }
    if (!LaunchBackend(runtime_layout_, selected_katago_, port, attempt,
                       &attempt_error)) {
      Log(L"Backend launch attempt " + std::to_wstring(attempt) +
          L" failed: " + attempt_error);
      StopBackendProcess(false);
      continue;
    }

    std::string instance_id;
    if (PollHealth(port, &instance_id, &attempt_error)) {
      configuration_.host = "127.0.0.1";
      configuration_.port = port;
      configuration_.instance_id = instance_id;
      ready_ = true;
      Log(L"Backend ready on dynamic loopback port " +
          std::to_wstring(port) + L"; instance " +
          WideFromUtf8(instance_id));
      return true;
    }

    Log(L"Backend readiness attempt " + std::to_wstring(attempt) +
        L" failed: " + attempt_error);
    StopBackendProcess(false);
  }

  *error_message =
      L"The packaged LogosGo backend did not become ready after " +
      std::to_wstring(kMaximumLaunchAttempts) +
      L" bounded attempts. See " + runner_log_path_.wstring();
  const std::wstring preserved = *error_message;
  Stop();
  *error_message = preserved;
  return false;
}

void BackendManager::Stop() {
  if (IsValidHandle(backend_process_)) {
    Log(L"Stopping backend");
    const bool shutdown_sent = ready_ && SendShutdownRequest();
    if (shutdown_sent &&
        ::WaitForSingleObject(backend_process_, kShutdownTimeoutMs) ==
            WAIT_OBJECT_0) {
      Log(L"Backend completed graceful shutdown");
      StopBackendProcess(false);
    } else {
      Log(L"Graceful shutdown did not complete; terminating the Job Object");
      StopBackendProcess(true);
    }
  }

  ready_ = false;
  configuration_ = BackendConfiguration{};
  selected_katago_.clear();
  CloseRuntimeHandles();
}

bool BackendManager::ResolveRuntimeLayout(RuntimeLayout* layout,
                                          std::wstring* error_message) {
  std::filesystem::path executable_directory;
  if (!ExecutableDirectory(&executable_directory, error_message)) {
    return false;
  }

  layout->runtime_root = executable_directory / L"runtime";
  layout->backend_executable =
      layout->runtime_root / L"backend" / L"logosgo_backend" /
      L"logosgo_backend.exe";
  layout->opencl_executable =
      layout->runtime_root / L"katago" / L"opencl" / L"katago.exe";
  layout->eigen_executable =
      layout->runtime_root / L"katago" / L"eigen" / L"katago.exe";
  layout->model_file = layout->runtime_root / L"model" / L"model.bin.gz";
  layout->config_file =
      layout->runtime_root / L"config" / L"analysis.cfg";
  layout->corpus_file =
      layout->runtime_root / L"data" / L"logosgo_corpus_full.csv";

  const std::array<std::pair<const wchar_t*, std::filesystem::path>, 5>
      required = {{{L"backend executable", layout->backend_executable},
                   {L"Eigen fallback", layout->eigen_executable},
                   {L"frozen model", layout->model_file},
                   {L"analysis config", layout->config_file},
                   {L"commentary corpus", layout->corpus_file}}};
  for (const auto& item : required) {
    if (!IsRegularFile(item.second)) {
      *error_message = L"Packaged LogosGo runtime is incomplete (missing " +
                       std::wstring(item.first) + L"): " +
                       item.second.wstring();
      return false;
    }
  }
  return true;
}

bool BackendManager::InitializeWritablePaths(std::wstring* error_message) {
  std::wstring local_app_data;
  if (!ReadEnvironmentVariable(L"LOCALAPPDATA", &local_app_data)) {
    std::wstring user_profile;
    if (!ReadEnvironmentVariable(L"USERPROFILE", &user_profile)) {
      *error_message =
          L"Neither LOCALAPPDATA nor USERPROFILE is available for LogosGo logs.";
      return false;
    }
    local_app_data =
        (std::filesystem::path(user_profile) / L"AppData" / L"Local").wstring();
  }

  logs_directory_ = std::filesystem::path(local_app_data) / L"LogosGo" / L"Logs";
  if (!logs_directory_.is_absolute()) {
    *error_message = L"The LogosGo log directory is not absolute: " +
                     logs_directory_.wstring();
    return false;
  }
  std::error_code error;
  std::filesystem::create_directories(logs_directory_, error);
  if (error || !std::filesystem::is_directory(logs_directory_, error)) {
    *error_message = L"Cannot create the LogosGo log directory: " +
                     logs_directory_.wstring();
    return false;
  }

  runner_log_ = OpenUniqueLog(L"runner", false, &runner_log_path_, error_message);
  return IsValidHandle(runner_log_);
}

bool BackendManager::InitializeJob(std::wstring* error_message) {
  job_ = ::CreateJobObjectW(nullptr, nullptr);
  if (!IsValidHandle(job_)) {
    *error_message =
        L"Cannot create the LogosGo Job Object: " + WindowsError(::GetLastError());
    return false;
  }

  JOBOBJECT_EXTENDED_LIMIT_INFORMATION information{};
  information.BasicLimitInformation.LimitFlags =
      JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
  if (!::SetInformationJobObject(job_, JobObjectExtendedLimitInformation,
                                 &information, sizeof(information))) {
    *error_message = L"Cannot configure kill-on-close Job Object: " +
                     WindowsError(::GetLastError());
    return false;
  }
  return true;
}

bool BackendManager::InitializeWinsock(std::wstring* error_message) {
  WSADATA data{};
  const int result = ::WSAStartup(MAKEWORD(2, 2), &data);
  if (result != 0) {
    *error_message = L"WSAStartup failed: " + std::to_wstring(result);
    return false;
  }
  winsock_initialized_ = true;
  return true;
}

bool BackendManager::GenerateInstanceToken(std::wstring* error_message) {
  std::array<uint8_t, 32> random_bytes{};
  const NTSTATUS status = ::BCryptGenRandom(
      nullptr, random_bytes.data(), static_cast<ULONG>(random_bytes.size()),
      BCRYPT_USE_SYSTEM_PREFERRED_RNG);
  if (status != 0) {
    *error_message = L"BCryptGenRandom failed while creating the instance token.";
    return false;
  }
  configuration_.instance_token =
      Base64UrlEncode(random_bytes.data(), random_bytes.size());
  if (configuration_.instance_token.size() < 40) {
    *error_message = L"Generated instance token did not meet the entropy contract.";
    return false;
  }
  configuration_.instance_id =
      InstanceIdForToken(configuration_.instance_token);
  if (configuration_.instance_id.empty()) {
    *error_message = L"Cannot derive the backend identity from the instance token.";
    return false;
  }
  return true;
}

bool BackendManager::SelectKataGo(const RuntimeLayout& layout,
                                  std::filesystem::path* selected,
                                  std::wstring* error_message) {
  if (IsRegularFile(layout.opencl_executable)) {
    const ProbeResult opencl =
        ProbeKataGo(L"OpenCL", layout.opencl_executable, layout);
    Log(L"OpenCL probe: " + opencl.detail + L"; log=" +
        opencl.log_file.wstring());
    if (opencl.ready) {
      *selected = layout.opencl_executable;
      Log(L"Selected KataGo OpenCL runtime");
      return true;
    }
  } else {
    Log(L"OpenCL runtime is absent; evaluating non-AVX2 Eigen fallback");
  }

  const ProbeResult eigen =
      ProbeKataGo(L"Eigen", layout.eigen_executable, layout);
  Log(L"Eigen probe: " + eigen.detail + L"; log=" +
      eigen.log_file.wstring());
  if (eigen.ready) {
    *selected = layout.eigen_executable;
    Log(L"Selected KataGo non-AVX2 Eigen fallback");
    return true;
  }

  *error_message =
      L"Neither KataGo OpenCL nor the non-AVX2 Eigen fallback initialized. "
      L"See probe logs in " +
      logs_directory_.wstring();
  return false;
}

BackendManager::ProbeResult BackendManager::ProbeKataGo(
    const std::wstring& backend_name,
    const std::filesystem::path& executable,
    const RuntimeLayout& layout) {
  ProbeResult result;
  std::wstring log_error;
  HANDLE output = OpenUniqueLog(L"katago-probe-" + backend_name, true,
                                &result.log_file, &log_error);
  if (!IsValidHandle(output)) {
    result.detail = L"cannot create probe log: " + log_error;
    return result;
  }

  PROCESS_INFORMATION process{};
  std::wstring launch_error;
  const std::vector<std::wstring> arguments = {
      L"analysis", L"-model", layout.model_file.wstring(), L"-config",
      layout.config_file.wstring()};
  const bool launched = LaunchJobProcess(
      executable, arguments, logs_directory_, output, &process, &launch_error);
  ::CloseHandle(output);
  if (!launched) {
    result.detail = L"launch failed: " + launch_error;
    return result;
  }

  const ULONGLONG deadline = ::GetTickCount64() + kProbeTimeoutMs;
  while (::GetTickCount64() < deadline) {
    const std::string diagnostics = ReadDiagnosticFile(result.log_file);
    if (diagnostics.find(kKataGoReadyMarker) != std::string::npos) {
      result.ready = true;
      result.detail = L"initialized and reached the analysis-ready marker";
      ::TerminateProcess(process.hProcess, 0);
      ::WaitForSingleObject(process.hProcess, 5000);
      ::CloseHandle(process.hProcess);
      return result;
    }

    const DWORD wait = ::WaitForSingleObject(process.hProcess, 200);
    if (wait == WAIT_OBJECT_0) {
      DWORD exit_code = 0;
      ::GetExitCodeProcess(process.hProcess, &exit_code);
      result.detail = L"exited before readiness with code " +
                      std::to_wstring(exit_code);
      ::CloseHandle(process.hProcess);
      return result;
    }
    if (wait == WAIT_FAILED) {
      result.detail =
          L"probe wait failed: " + WindowsError(::GetLastError());
      ::TerminateProcess(process.hProcess, 1);
      ::WaitForSingleObject(process.hProcess, 5000);
      ::CloseHandle(process.hProcess);
      return result;
    }
  }

  result.detail = L"timed out before readiness";
  ::TerminateProcess(process.hProcess, 1);
  ::WaitForSingleObject(process.hProcess, 5000);
  ::CloseHandle(process.hProcess);
  return result;
}

bool BackendManager::AllocateLoopbackPort(uint16_t* port,
                                          std::wstring* error_message) {
  SOCKET socket_handle = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (socket_handle == INVALID_SOCKET) {
    *error_message = L"Cannot create loopback socket: " +
                     std::to_wstring(::WSAGetLastError());
    return false;
  }

  sockaddr_in address{};
  address.sin_family = AF_INET;
  address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  address.sin_port = 0;
  if (::bind(socket_handle, reinterpret_cast<sockaddr*>(&address),
             static_cast<int>(sizeof(address))) == SOCKET_ERROR) {
    *error_message =
        L"Cannot bind an ephemeral loopback port: " +
        std::to_wstring(::WSAGetLastError());
    ::closesocket(socket_handle);
    return false;
  }

  int address_size = static_cast<int>(sizeof(address));
  if (::getsockname(socket_handle, reinterpret_cast<sockaddr*>(&address),
                    &address_size) == SOCKET_ERROR) {
    *error_message = L"Cannot read the allocated loopback port: " +
                     std::to_wstring(::WSAGetLastError());
    ::closesocket(socket_handle);
    return false;
  }
  *port = ntohs(address.sin_port);
  ::closesocket(socket_handle);
  return *port != 0;
}

bool BackendManager::LaunchBackend(
    const RuntimeLayout& layout,
    const std::filesystem::path& katago_executable,
    uint16_t port,
    int attempt,
    std::wstring* error_message) {
  HANDLE output = OpenUniqueLog(
      L"backend-attempt-" + std::to_wstring(attempt), true,
      &backend_log_path_, error_message);
  if (!IsValidHandle(output)) {
    return false;
  }

  const std::vector<std::wstring> arguments = {
      L"--port",
      std::to_wstring(port),
      L"--instance-token",
      WideFromUtf8(configuration_.instance_token),
      L"--resource-root",
      layout.runtime_root.wstring(),
      L"--katago-executable",
      katago_executable.wstring(),
      L"--parent-pid",
      std::to_wstring(::GetCurrentProcessId())};
  PROCESS_INFORMATION process{};
  const bool launched = LaunchJobProcess(
      layout.backend_executable, arguments, logs_directory_, output, &process,
      error_message);
  ::CloseHandle(output);
  if (!launched) {
    return false;
  }
  backend_process_ = process.hProcess;
  Log(L"Launched backend attempt " + std::to_wstring(attempt) +
      L" on dynamic port " + std::to_wstring(port) + L"; output=" +
      backend_log_path_.wstring());
  return true;
}

bool BackendManager::PollHealth(uint16_t port,
                                std::string* instance_id,
                                std::wstring* error_message) {
  const ULONGLONG deadline = ::GetTickCount64() + kHealthTimeoutMs;
  while (::GetTickCount64() < deadline) {
    if (::WaitForSingleObject(backend_process_, 0) == WAIT_OBJECT_0) {
      DWORD exit_code = 0;
      ::GetExitCodeProcess(backend_process_, &exit_code);
      *error_message = L"Backend exited before readiness with code " +
                       std::to_wstring(exit_code) + L"; output=" +
                       backend_log_path_.wstring();
      return false;
    }

    DWORD status = 0;
    std::string body;
    if (HttpRequest(L"GET", kHealthPath, port, 1000, &status, &body) &&
        status == 200) {
      const std::string compact = CompactJson(body);
      std::string received_instance_id;
      if (JsonHasString(compact, "service", "LogosGoBackend") &&
          JsonHasInteger(compact, "api_schema_version", 1) &&
          JsonHasBoolean(compact, "ready", true) &&
          JsonHasBoolean(compact, "token_verified", true) &&
          JsonString(compact, "instance_id", &received_instance_id) &&
          received_instance_id == configuration_.instance_id) {
        *instance_id = received_instance_id;
        return true;
      }
      *error_message = L"Backend health identity did not match the LogosGo contract.";
      return false;
    }
    ::Sleep(250);
  }
  *error_message = L"Timed out waiting for authenticated backend readiness; output=" +
                   backend_log_path_.wstring();
  return false;
}

bool BackendManager::SendShutdownRequest() {
  DWORD status = 0;
  std::string body;
  const bool sent =
      HttpRequest(L"POST", kShutdownPath, configuration_.port, 1500, &status,
                  &body);
  if (!sent || status != 200) {
    Log(L"Authenticated shutdown request failed or returned non-200 status");
    return false;
  }
  return true;
}

bool BackendManager::HttpRequest(const wchar_t* method,
                                 const wchar_t* path,
                                 uint16_t port,
                                 DWORD timeout_ms,
                                 DWORD* status_code,
                                 std::string* response_body) {
  HINTERNET session = ::WinHttpOpen(
      L"LogosGo/1.0.0", WINHTTP_ACCESS_TYPE_NO_PROXY,
      WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
  if (session == nullptr) {
    return false;
  }
  ::WinHttpSetTimeouts(session, static_cast<int>(timeout_ms),
                       static_cast<int>(timeout_ms),
                       static_cast<int>(timeout_ms),
                       static_cast<int>(timeout_ms));
  HINTERNET connection = ::WinHttpConnect(session, L"127.0.0.1", port, 0);
  if (connection == nullptr) {
    ::WinHttpCloseHandle(session);
    return false;
  }
  HINTERNET request = ::WinHttpOpenRequest(
      connection, method, path, nullptr, WINHTTP_NO_REFERER,
      WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
  if (request == nullptr) {
    ::WinHttpCloseHandle(connection);
    ::WinHttpCloseHandle(session);
    return false;
  }

  const std::wstring headers = std::wstring(kInstanceHeader) + L": " +
                               WideFromUtf8(configuration_.instance_token) +
                               L"\r\n";
  bool success = ::WinHttpSendRequest(
                     request, headers.c_str(),
                     static_cast<DWORD>(headers.size()), WINHTTP_NO_REQUEST_DATA,
                     0, 0, 0) != FALSE &&
                 ::WinHttpReceiveResponse(request, nullptr) != FALSE;
  if (success) {
    DWORD status_size = sizeof(*status_code);
    success = ::WinHttpQueryHeaders(
                  request,
                  WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                  WINHTTP_HEADER_NAME_BY_INDEX, status_code, &status_size,
                  WINHTTP_NO_HEADER_INDEX) != FALSE;
  }

  response_body->clear();
  while (success) {
    DWORD available = 0;
    if (!::WinHttpQueryDataAvailable(request, &available)) {
      success = false;
      break;
    }
    if (available == 0) {
      break;
    }
    const size_t original_size = response_body->size();
    response_body->resize(original_size + available);
    DWORD read = 0;
    if (!::WinHttpReadData(request, response_body->data() + original_size,
                           available, &read)) {
      success = false;
      break;
    }
    response_body->resize(original_size + read);
  }

  ::WinHttpCloseHandle(request);
  ::WinHttpCloseHandle(connection);
  ::WinHttpCloseHandle(session);
  return success;
}

bool BackendManager::LaunchJobProcess(
    const std::filesystem::path& executable,
    const std::vector<std::wstring>& arguments,
    const std::filesystem::path& working_directory,
    HANDLE output_handle,
    PROCESS_INFORMATION* process,
    std::wstring* error_message) {
  SECURITY_ATTRIBUTES security{};
  security.nLength = sizeof(security);
  security.bInheritHandle = TRUE;
  HANDLE null_input = ::CreateFileW(
      L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &security,
      OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (!IsValidHandle(null_input)) {
    *error_message =
        L"Cannot open NUL for child stdin: " + WindowsError(::GetLastError());
    return false;
  }
  if (!::SetHandleInformation(output_handle, HANDLE_FLAG_INHERIT,
                              HANDLE_FLAG_INHERIT)) {
    *error_message = L"Cannot make the child output log inheritable: " +
                     WindowsError(::GetLastError());
    ::CloseHandle(null_input);
    return false;
  }

  SIZE_T attribute_size = 0;
  if (::InitializeProcThreadAttributeList(nullptr, 1, 0, &attribute_size) ||
      ::GetLastError() != ERROR_INSUFFICIENT_BUFFER || attribute_size == 0) {
    *error_message = L"Cannot size the child handle list: " +
                     WindowsError(::GetLastError());
    ::CloseHandle(null_input);
    return false;
  }
  std::vector<uint8_t> attribute_buffer(attribute_size);
  auto* attribute_list = reinterpret_cast<PPROC_THREAD_ATTRIBUTE_LIST>(
      attribute_buffer.data());
  if (!::InitializeProcThreadAttributeList(attribute_list, 1, 0,
                                           &attribute_size)) {
    *error_message = L"Cannot initialize the child handle list: " +
                     WindowsError(::GetLastError());
    ::CloseHandle(null_input);
    return false;
  }

  HANDLE inherited_handles[2] = {output_handle, null_input};
  if (!::UpdateProcThreadAttribute(
          attribute_list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
          inherited_handles, sizeof(inherited_handles), nullptr, nullptr)) {
    *error_message = L"Cannot restrict inherited child handles: " +
                     WindowsError(::GetLastError());
    ::DeleteProcThreadAttributeList(attribute_list);
    ::CloseHandle(null_input);
    return false;
  }

  STARTUPINFOEXW startup{};
  startup.StartupInfo.cb = sizeof(startup);
  startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
  startup.StartupInfo.hStdInput = null_input;
  startup.StartupInfo.hStdOutput = output_handle;
  startup.StartupInfo.hStdError = output_handle;
  startup.lpAttributeList = attribute_list;

  std::wstring command_line = BuildCommandLine(executable, arguments);
  std::vector<wchar_t> mutable_command(command_line.begin(), command_line.end());
  mutable_command.push_back(L'\0');

  const DWORD flags = CREATE_NO_WINDOW | CREATE_SUSPENDED |
                      EXTENDED_STARTUPINFO_PRESENT;
  const BOOL created = ::CreateProcessW(
      executable.c_str(), mutable_command.data(), nullptr, nullptr, TRUE, flags,
      nullptr, working_directory.c_str(), &startup.StartupInfo, process);
  const DWORD create_error = created ? ERROR_SUCCESS : ::GetLastError();
  ::DeleteProcThreadAttributeList(attribute_list);
  ::CloseHandle(null_input);
  if (!created) {
    *error_message =
        L"CreateProcessW failed: " + WindowsError(create_error);
    return false;
  }

  if (!::AssignProcessToJobObject(job_, process->hProcess)) {
    const DWORD assign_error = ::GetLastError();
    ::TerminateProcess(process->hProcess, 1);
    ::WaitForSingleObject(process->hProcess, 5000);
    ::CloseHandle(process->hThread);
    ::CloseHandle(process->hProcess);
    process->hThread = nullptr;
    process->hProcess = nullptr;
    *error_message = L"Cannot assign child to kill-on-close Job Object: " +
                     WindowsError(assign_error);
    return false;
  }

  if (::ResumeThread(process->hThread) == static_cast<DWORD>(-1)) {
    const DWORD resume_error = ::GetLastError();
    ::TerminateProcess(process->hProcess, 1);
    ::WaitForSingleObject(process->hProcess, 5000);
    ::CloseHandle(process->hThread);
    ::CloseHandle(process->hProcess);
    process->hThread = nullptr;
    process->hProcess = nullptr;
    *error_message =
        L"Cannot resume child process: " + WindowsError(resume_error);
    return false;
  }
  ::CloseHandle(process->hThread);
  process->hThread = nullptr;
  return true;
}

HANDLE BackendManager::OpenUniqueLog(const std::wstring& prefix,
                                     bool inheritable,
                                     std::filesystem::path* path,
                                     std::wstring* error_message) {
  SECURITY_ATTRIBUTES security{};
  security.nLength = sizeof(security);
  security.bInheritHandle = inheritable ? TRUE : FALSE;
  const std::wstring timestamp = TimestampForFileName();
  for (int suffix = 0; suffix < 100; ++suffix) {
    std::wstring file_name = prefix + L"-" + timestamp;
    if (suffix != 0) {
      file_name += L"-" + std::to_wstring(suffix);
    }
    file_name += L".log";
    const std::filesystem::path candidate = logs_directory_ / file_name;
    HANDLE handle = ::CreateFileW(
        candidate.c_str(), GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        inheritable ? &security : nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL,
        nullptr);
    if (IsValidHandle(handle)) {
      *path = candidate;
      return handle;
    }
    if (::GetLastError() != ERROR_FILE_EXISTS) {
      *error_message = L"Cannot create log file " + candidate.wstring() +
                       L": " + WindowsError(::GetLastError());
      return INVALID_HANDLE_VALUE;
    }
  }
  *error_message = L"Cannot allocate a unique LogosGo log file name.";
  return INVALID_HANDLE_VALUE;
}

void BackendManager::Log(const std::wstring& message) {
  if (!IsValidHandle(runner_log_)) {
    return;
  }
  const std::string line =
      Utf8FromWide(L"[" + TimestampForLogLine() + L"] " + message + L"\r\n");
  DWORD written = 0;
  ::WriteFile(runner_log_, line.data(), static_cast<DWORD>(line.size()),
              &written, nullptr);
  ::FlushFileBuffers(runner_log_);
}

void BackendManager::StopBackendProcess(bool terminate_job) {
  if (terminate_job && IsValidHandle(job_)) {
    ::TerminateJobObject(job_, 1);
  } else if (IsValidHandle(backend_process_) &&
             ::WaitForSingleObject(backend_process_, 0) == WAIT_TIMEOUT) {
    ::TerminateProcess(backend_process_, 1);
  }
  if (IsValidHandle(backend_process_)) {
    ::WaitForSingleObject(backend_process_, 5000);
    ::CloseHandle(backend_process_);
    backend_process_ = nullptr;
  }
}

void BackendManager::CloseRuntimeHandles() {
  if (IsValidHandle(job_)) {
    ::CloseHandle(job_);
    job_ = nullptr;
  }
  if (winsock_initialized_) {
    ::WSACleanup();
    winsock_initialized_ = false;
  }
  if (IsValidHandle(runner_log_)) {
    ::FlushFileBuffers(runner_log_);
    ::CloseHandle(runner_log_);
    runner_log_ = INVALID_HANDLE_VALUE;
  }
}
