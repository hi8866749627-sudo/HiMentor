import { DEFAULT_API_BASE_URL } from "./constants";

let CURRENT_API_BASE_URL = DEFAULT_API_BASE_URL;

export function setApiBaseUrl(url) {
  const next = String(url || "").trim().replace(/\/+$/, "");
  if (next) {
    CURRENT_API_BASE_URL = next;
  }
}

export function getApiBaseUrl() {
  return CURRENT_API_BASE_URL;
}

async function request(path, options = {}, token = "") {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const response = await fetch(`${CURRENT_API_BASE_URL}${path}`, {
    ...options,
    headers,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.msg || "Request failed");
  }
  return data;
}

export function login(mentor, password) {
  return request("/api/mobile/login/", {
    method: "POST",
    body: JSON.stringify({ mentor, password }),
  });
}

export function logout(token) {
  return request("/api/mobile/logout/", { method: "POST", body: "{}" }, token);
}

export function getModules(token, moduleId = "") {
  const query = moduleId ? `?module_id=${moduleId}` : "";
  return request(`/api/mobile/modules/${query}`, { method: "GET" }, token);
}

export function getWeeks(token, moduleId) {
  return request(`/api/mobile/weeks/?module_id=${moduleId}`, { method: "GET" }, token);
}

export function getCalls(token, week, moduleId) {
  return request(`/api/mobile/calls/?week=${week}&module_id=${moduleId}`, { method: "GET" }, token);
}

export function saveCall(token, payload) {
  return request(
    "/api/mobile/save-call/",
    { method: "POST", body: JSON.stringify(payload) },
    token
  );
}

export function getRetryList(token, week, moduleId) {
  return request(`/api/mobile/retry-list/?week=${week}&module_id=${moduleId}`, { method: "GET" }, token);
}

export function markMessage(token, id, moduleId) {
  return request(
    "/api/mobile/mark-message/",
    { method: "POST", body: JSON.stringify({ id, module_id: moduleId }) },
    token
  );
}

export function getResultCycles(token, moduleId) {
  return request(`/api/mobile/result-cycles/?module_id=${moduleId}`, { method: "GET" }, token);
}

export function getResultCalls(token, uploadId = "", moduleId = "") {
  const query = uploadId ? `?upload_id=${uploadId}&module_id=${moduleId}` : `?module_id=${moduleId}`;
  return request(`/api/mobile/result-calls/${query}`, { method: "GET" }, token);
}

export function saveResultCall(token, payload) {
  return request(
    "/api/mobile/save-result-call/",
    { method: "POST", body: JSON.stringify(payload) },
    token
  );
}

export function getResultRetryList(token, uploadId, moduleId) {
  return request(`/api/mobile/result-retry-list/?upload_id=${uploadId}&module_id=${moduleId}`, { method: "GET" }, token);
}

export function markResultMessage(token, id, moduleId) {
  return request(
    "/api/mobile/mark-result-message/",
    { method: "POST", body: JSON.stringify({ id, module_id: moduleId }) },
    token
  );
}

export function getResultReport(token, uploadId = "", moduleId = "") {
  const query = uploadId ? `?upload_id=${uploadId}&module_id=${moduleId}` : `?module_id=${moduleId}`;
  return request(`/api/mobile/result-report/${query}`, { method: "GET" }, token);
}

export function getOtherCalls(token, moduleId) {
  return request(`/api/mobile/other-calls/?module_id=${moduleId}`, { method: "GET" }, token);
}

export function saveOtherCall(token, payload) {
  return request(
    "/api/mobile/save-other-call/",
    { method: "POST", body: JSON.stringify(payload) },
    token
  );
}

export function staffLogin(username, password) {
  return request("/api/mobile/staff/login/", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function getStaffModules(token, moduleId = "") {
  const query = moduleId ? `?module_id=${moduleId}` : "";
  return request(`/api/mobile/staff/modules/${query}`, { method: "GET" }, token);
}

export function getStaffStudents(token, moduleId = "", opts = {}) {
  const params = [];
  if (moduleId) params.push(`module_id=${moduleId}`);
  if (opts.page) params.push(`page=${opts.page}`);
  if (opts.page_size) params.push(`page_size=${opts.page_size}`);
  if (opts.q) params.push(`q=${encodeURIComponent(opts.q)}`);
  const query = params.length ? `?${params.join("&")}` : "";
  return request(`/api/mobile/staff/students/${query}`, { method: "GET" }, token);
}

export function getStaffWeeks(token, moduleId = "") {
  const query = moduleId ? `?module_id=${moduleId}` : "";
  return request(`/api/mobile/staff/weeks/${query}`, { method: "GET" }, token);
}

export function getStaffAttendance(token, week, moduleId = "") {
  const query = `?week=${week}${moduleId ? `&module_id=${moduleId}` : ""}`;
  return request(`/api/mobile/staff/attendance/${query}`, { method: "GET" }, token);
}

export function getStaffResultCycles(token, moduleId = "") {
  const query = moduleId ? `?module_id=${moduleId}` : "";
  return request(`/api/mobile/staff/result-cycles/${query}`, { method: "GET" }, token);
}

export function getStaffResultRows(token, uploadId = "", moduleId = "", opts = {}) {
  const params = [];
  if (uploadId) params.push(`upload_id=${uploadId}`);
  if (moduleId) params.push(`module_id=${moduleId}`);
  if (opts.page) params.push(`page=${opts.page}`);
  if (opts.page_size) params.push(`page_size=${opts.page_size}`);
  if (opts.q) params.push(`q=${encodeURIComponent(opts.q)}`);
  if (opts.fail_filter) params.push(`fail_filter=${encodeURIComponent(opts.fail_filter)}`);
  const query = params.length ? `?${params.join("&")}` : "";
  return request(`/api/mobile/staff/result-rows/${query}`, { method: "GET" }, token);
}

export function getStaffControlSummary(token, moduleId = "", week = "", uploadId = "") {
  const params = [];
  if (moduleId) params.push(`module_id=${moduleId}`);
  if (week) params.push(`week=${week}`);
  if (uploadId) params.push(`upload_id=${uploadId}`);
  const query = params.length ? `?${params.join("&")}` : "";
  return request(`/api/mobile/staff/control-summary/${query}`, { method: "GET" }, token);
}

export function getStaffAttendanceReport(token, moduleId = "", week = "") {
  const params = [];
  if (moduleId) params.push(`module_id=${moduleId}`);
  if (week) params.push(`week=${week}`);
  const query = params.length ? `?${params.join("&")}` : "";
  return request(`/api/mobile/staff/attendance-report/${query}`, { method: "GET" }, token);
}

export function getStaffResultReport(token, moduleId = "", uploadId = "") {
  const params = [];
  if (moduleId) params.push(`module_id=${moduleId}`);
  if (uploadId) params.push(`upload_id=${uploadId}`);
  const query = params.length ? `?${params.join("&")}` : "";
  return request(`/api/mobile/staff/result-report/${query}`, { method: "GET" }, token);
}

export function getStaffSubjects(token, moduleId = "") {
  const query = moduleId ? `?module_id=${moduleId}` : "";
  return request(`/api/mobile/staff/subjects/${query}`, { method: "GET" }, token);
}

export function getStaffHomeSummary(token) {
  return request("/api/mobile/staff/home-summary/", { method: "GET" }, token);
}

export function getStaffModulesManage(token) {
  return request("/api/mobile/staff/modules-manage/", { method: "GET" }, token);
}

export function createStaffModule(token, payload) {
  return request("/api/mobile/staff/modules-manage/", { method: "POST", body: JSON.stringify(payload) }, token);
}

export function toggleStaffModule(token, moduleId, action) {
  return request(
    "/api/mobile/staff/module-toggle/",
    { method: "POST", body: JSON.stringify({ module_id: moduleId, action }) },
    token
  );
}
