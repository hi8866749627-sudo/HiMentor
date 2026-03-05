import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  FlatList,
  Linking,
  Modal,
  Platform,
  SafeAreaView,
  Share,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  StatusBar as RNStatusBar,
  useColorScheme,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Clipboard from "expo-clipboard";
import * as Notifications from "expo-notifications";
import { StatusBar } from "expo-status-bar";
import {
  getCalls,
  getModules,
  getOtherCalls,
  getResultCalls,
  getResultCycles,
  getResultReport,
  getResultRetryList,
  getRetryList,
  getWeeks,
  login,
  logout,
  markMessage,
  markResultMessage,
  saveOtherCall,
  saveCall,
  saveResultCall,
  setApiBaseUrl,
} from "../api";
import {
  LIVE_API_BASE_URL,
} from "../constants";

const talkedOptions = ["father", "mother", "guardian", "student"];
const SESSION_KEY = "easymentor_session_v1";
const WEEK_KEY = "easymentor_week_v1";
const RETRY_COUNT_KEY = "easymentor_retry_count_v1";
const RESULT_UPLOAD_KEY = "easymentor_result_upload_v1";
const MODULE_KEY = "easymentor_module_v1";
const API_BASE_URL_KEY = "easymentor_api_base_url_v1";
const THEME_KEY = "easymentor_theme_v1";
const MENU_ITEMS = [
  { key: "attendance_calls", label: "Attendance" },
  { key: "result_calls", label: "Results" },
  { key: "other_calls", label: "Direct" },
  { key: "report", label: "Report" },
  { key: "message", label: "Message" },
];

const MENTOR_SUBMENUS = {
  attendance_calls: [
    { key: "calls", label: "Calls" },
    { key: "retry", label: "Retry" },
    { key: "report", label: "Report" },
  ],
  result_calls: [
    { key: "calls", label: "Calls" },
    { key: "retry", label: "Retry" },
    { key: "report", label: "Report" },
  ],
  other_calls: [
    { key: "calls", label: "Calls" },
    { key: "summary", label: "Summary" },
  ],
  report: [
    { key: "attendance", label: "Attendance" },
    { key: "result", label: "Result" },
    { key: "direct", label: "Direct" },
  ],
  message: [{ key: "message", label: "To Mentees" }],
};

const MENTOR_THEME = {
  light: {
    pageBg: "#F7F9FC",
    headerBg: "#ffffff",
    headerText: "#0f172a",
    subText: "#64748b",
    subMenuChipBg: "#ffffff",
    subMenuChipBorder: "#d7dfeb",
    subMenuChipText: "#334155",
    subMenuChipActiveBg: "#2563eb",
    subMenuChipActiveText: "#ffffff",
    cardBg: "#ffffff",
    cardBorder: "#d7dfeb",
    bottomBarBg: "#ffffff",
    bottomBarBorder: "#d7dfeb",
    tabText: "#64748b",
    tabActiveBg: "#dbeafe",
    tabActiveText: "#1e40af",
  },
  dark: {
    pageBg: "#0b1220",
    headerBg: "#111827",
    headerText: "#f8fafc",
    subText: "#94a3b8",
    subMenuChipBg: "#0f172a",
    subMenuChipBorder: "#334155",
    subMenuChipText: "#cbd5e1",
    subMenuChipActiveBg: "#1d4ed8",
    subMenuChipActiveText: "#ffffff",
    cardBg: "#111827",
    cardBorder: "#334155",
    bottomBarBg: "#0f172a",
    bottomBarBorder: "#334155",
    tabText: "#dbeafe",
    tabActiveBg: "#1d4ed8",
    tabActiveText: "#ffffff",
  },
};

const DS = {
  s8: 8,
  s16: 16,
  s24: 24,
  s32: 32,
  radiusCard: 16,
  radiusBtn: 12,
  radiusInput: 12,
};

const COLOR_SYSTEM = {
  background: "#F7F9FC",
  primary: "#2563eb",
  success: "#16a34a",
  waiting: "#f59e0b",
  danger: "#dc2626",
  neutral: "#64748b",
  textPrimary: "#0f172a",
  textSecondary: "#475569",
  border: "#d7dfeb",
};

function statusBadgeStyle(status) {
  if (status === "received") return { bg: "#16a34a", text: "Received" };
  if (status === "not_received") return { bg: "#f59e0b", text: "Not Received" };
  if (status === "pre_informed") return { bg: "#6b7280", text: "Pre-informed" };
  return { bg: "#2563eb", text: "Pending" };
}

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

async function ensureNotificationPermission() {
  const perms = await Notifications.getPermissionsAsync();
  if (perms.status === "granted") {
    return true;
  }
  const req = await Notifications.requestPermissionsAsync();
  return req.status === "granted";
}

async function configureNotificationChannel() {
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#0f5e9c",
    });
  }
}

function statusPriority(status) {
  if (status === "not_received") {
    return 0;
  }
  if (status === "received") {
    return 2;
  }
  return 1;
}

function orderCallRecords(items) {
  const list = [...(items || [])];
  list.sort((a, b) => {
    const p = statusPriority(a.final_status) - statusPriority(b.final_status);
    if (p !== 0) {
      return p;
    }
    const ra = Number(a?.student?.roll_no || 999999);
    const rb = Number(b?.student?.roll_no || 999999);
    return ra - rb;
  });
  return list;
}

export default function LegacyMentorApp({ onExitApp = null }) {
  const systemIsDark = useColorScheme() === "dark";
  const [themeMode, setThemeMode] = useState("system");
  const isDark = themeMode === "system" ? systemIsDark : themeMode === "dark";
  const palette = isDark ? MENTOR_THEME.dark : MENTOR_THEME.light;
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false);
  const [token, setToken] = useState("");
  const [mentorNameInput, setMentorNameInput] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [mentorPasswordInput, setMentorPasswordInput] = useState("");
  const [mentorName, setMentorName] = useState("");
  const [loading, setLoading] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [apiBaseUrl, setApiBaseUrlState] = useState(LIVE_API_BASE_URL);
  const [weeks, setWeeks] = useState([]);
  const [modules, setModules] = useState([]);
  const [selectedModuleId, setSelectedModuleId] = useState(null);
  const [selectedWeek, setSelectedWeek] = useState(null);
  const [records, setRecords] = useState([]);
  const [allDone, setAllDone] = useState(false);
  const [retryRecords, setRetryRecords] = useState([]);
  const [resultCycles, setResultCycles] = useState([]);
  const [selectedResultUpload, setSelectedResultUpload] = useState(null);
  const [resultRecords, setResultRecords] = useState([]);
  const [otherRecords, setOtherRecords] = useState([]);
  const [resultAllDone, setResultAllDone] = useState(false);
  const [resultRetryRecords, setResultRetryRecords] = useState([]);
  const [resultReport, setResultReport] = useState("");
  const [lastCallType, setLastCallType] = useState("attendance");
  const [activeMenu, setActiveMenu] = useState("attendance_calls");
  const [activeSubmenu, setActiveSubmenu] = useState("calls");
  const [messageDraft, setMessageDraft] = useState("Dear parent, please connect with mentor regarding student follow-up.");
  const [weekReportInput, setWeekReportInput] = useState("");

  const [activeCall, setActiveCall] = useState(null);
  const [callStart, setCallStart] = useState(0);
  const [modalVisible, setModalVisible] = useState(false);
  const [talked, setTalked] = useState("father");
  const [duration, setDuration] = useState("");
  const [remark, setRemark] = useState("");
  const [callReason, setCallReason] = useState("");

  const appState = useRef(AppState.currentState);
  const pollRef = useRef(null);

  const completedCount = useMemo(
    () => records.filter((x) => x.final_status).length,
    [records]
  );
  const resultCompletedCount = useMemo(
    () => resultRecords.filter((x) => x.final_status).length,
    [resultRecords]
  );
  const visibleRecords = useMemo(() => {
    if (activeMenu === "result_calls") {
      return resultRecords;
    }
    if (activeMenu === "other_calls") {
      return otherRecords;
    }
    return records;
  }, [records, resultRecords, otherRecords, activeMenu]);
  const visibleCompletedCount = useMemo(
    () => visibleRecords.filter((x) => x.final_status).length,
    [visibleRecords]
  );
  const reportStats = useMemo(() => {
    const total = records.length;
    const done = completedCount;
    const received = records.filter((x) => x.final_status === "received").length;
    const notReceived = records.filter((x) => x.final_status === "not_received").length;
    const preInformed = records.filter((x) => x.final_status === "pre_informed").length;
    const messageDone = records.filter((x) => x.message_sent).length;
    const avgDuration = (() => {
      const vals = records
        .filter((x) => x.final_status)
        .map((x) => Number(x.call_duration || x.duration_minutes || x.duration || 0))
        .filter((v) => Number.isFinite(v) && v > 0);
      if (!vals.length) return 0;
      return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
    })();
    return {
      total,
      done,
      received,
      notReceived,
      preInformed,
      pending: Math.max(0, total - done),
      messageDone,
      avgDuration,
    };
  }, [records, completedCount]);
  const resultReportStats = useMemo(() => {
    const total = resultRecords.length;
    const done = resultCompletedCount;
    const received = resultRecords.filter((x) => x.final_status === "received").length;
    const notReceived = resultRecords.filter((x) => x.final_status === "not_received").length;
    const preInformed = resultRecords.filter((x) => x.final_status === "pre_informed").length;
    const messageDone = resultRecords.filter((x) => x.message_sent).length;
    const avgDuration = (() => {
      const vals = resultRecords
        .filter((x) => x.final_status)
        .map((x) => Number(x.call_duration || x.duration_minutes || x.duration || 0))
        .filter((v) => Number.isFinite(v) && v > 0);
      if (!vals.length) return 0;
      return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
    })();
    return {
      total,
      done,
      received,
      notReceived,
      preInformed,
      pending: Math.max(0, total - done),
      messageDone,
      avgDuration,
    };
  }, [resultRecords, resultCompletedCount]);
  const otherCompletedCount = useMemo(
    () => otherRecords.filter((x) => x.final_status).length,
    [otherRecords]
  );
  const talkedChoiceOptions = useMemo(
    () =>
      lastCallType === "other"
        ? talkedOptions
        : talkedOptions.filter((opt) => opt !== "student"),
    [lastCallType]
  );
  const selectedModuleName = useMemo(() => {
    const found = modules.find((m) => m.module_id === selectedModuleId);
    return found ? found.name : "-";
  }, [modules, selectedModuleId]);
  const attendanceReportMessage = useMemo(
    () =>
      `Weekly WhatsApp Report\nWeek ${selectedWeek || "-"}\nTotal Defaulters: ${reportStats.total}\nCalls Done: ${reportStats.done}\nNot Received: ${reportStats.notReceived}\nPre-informed: ${reportStats.preInformed}\nAvg Duration: ${reportStats.avgDuration} mins`,
    [selectedWeek, reportStats]
  );
  const resultReportMessage = useMemo(
    () =>
      resultReport ||
      `Result Call WhatsApp Report\nUpload ${selectedResultUpload || "-"}\nTotal Defaulters: ${resultReportStats.total}\nCalls Done: ${resultReportStats.done}\nNot Received: ${resultReportStats.notReceived}\nPre-informed: ${resultReportStats.preInformed}\nAvg Duration: ${resultReportStats.avgDuration} mins`,
    [resultReport, selectedResultUpload, resultReportStats]
  );
  const directReportMessage = useMemo(() => {
    const received = otherRecords.filter((x) => x.final_status === "received").length;
    const notReceived = otherRecords.filter((x) => x.final_status === "not_received").length;
    const preInformed = otherRecords.filter((x) => x.final_status === "pre_informed").length;
    const avgDuration = (() => {
      const vals = otherRecords
        .filter((x) => x.final_status)
        .map((x) => Number(x.call_duration || x.duration_minutes || x.duration || 0))
        .filter((v) => Number.isFinite(v) && v > 0);
      if (!vals.length) return 0;
      return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
    })();
    return `Direct Call WhatsApp Report\nTotal Defaulters: ${otherRecords.length}\nCalls Done: ${otherCompletedCount}\nNot Received: ${notReceived}\nPre-informed: ${preInformed}\nAvg Duration: ${avgDuration} mins`;
  }, [otherRecords, otherCompletedCount]);

  async function storeSession(nextToken, nextMentorName) {
    await AsyncStorage.setItem(
      SESSION_KEY,
      JSON.stringify({ token: nextToken, mentorName: nextMentorName })
    );
  }

  async function clearSession() {
    await AsyncStorage.multiRemove([SESSION_KEY, WEEK_KEY, RETRY_COUNT_KEY, RESULT_UPLOAD_KEY]);
  }

  async function storeSelectedWeek(week) {
    if (!week) {
      await AsyncStorage.removeItem(WEEK_KEY);
      return;
    }
    await AsyncStorage.setItem(WEEK_KEY, String(week));
  }

  async function storeSelectedResultUpload(uploadId) {
    if (!uploadId) {
      await AsyncStorage.removeItem(RESULT_UPLOAD_KEY);
      return;
    }
    await AsyncStorage.setItem(RESULT_UPLOAD_KEY, String(uploadId));
  }

  async function storeSelectedModule(moduleId) {
    if (!moduleId) {
      await AsyncStorage.removeItem(MODULE_KEY);
      return;
    }
    await AsyncStorage.setItem(MODULE_KEY, String(moduleId));
  }

  async function storeApiBaseUrl(url) {
    const next = String(url || "").trim().replace(/\/+$/, "");
    await AsyncStorage.setItem(API_BASE_URL_KEY, next);
  }

  async function maybeNotifyRetryPending(week, currentRetryCount) {
    const prevRaw = await AsyncStorage.getItem(RETRY_COUNT_KEY);
    const prevCount = Number(prevRaw || 0);
    await AsyncStorage.setItem(RETRY_COUNT_KEY, String(currentRetryCount));

    if (currentRetryCount <= 0 || currentRetryCount <= prevCount) {
      return;
    }
    const allowed = await ensureNotificationPermission();
    if (!allowed) {
      return;
    }
    await Notifications.scheduleNotificationAsync({
      content: {
        title: "Retry Calls Pending",
        body: `Week ${week}: ${currentRetryCount} parents need retry calls.`,
      },
      trigger: null,
    });
  }

  async function loadResultDashboard(authToken, moduleId, preferredUploadId = null) {
    const cycleData = await getResultCycles(authToken, moduleId);
    const cycles = cycleData.cycles || [];
    setResultCycles(cycles);

    const chosenUpload =
      preferredUploadId || cycleData.latest_upload_id || (cycles.length ? cycles[0].upload_id : null);
    setSelectedResultUpload(chosenUpload || null);
    await storeSelectedResultUpload(chosenUpload || "");

    if (!chosenUpload) {
      setResultRecords([]);
      setResultAllDone(false);
      setResultRetryRecords([]);
      setResultReport("");
      return;
    }

    const callData = await getResultCalls(authToken, chosenUpload, moduleId);
    const ordered = orderCallRecords(callData.records || []);
    setResultRecords(ordered);
    setResultAllDone(Boolean(callData.all_done));

    const reportData = await getResultReport(authToken, chosenUpload, moduleId);
    setResultReport(reportData.report || "");

    if (callData.all_done) {
      const retryData = await getResultRetryList(authToken, chosenUpload, moduleId);
      setResultRetryRecords(retryData.records || []);
    } else {
      setResultRetryRecords([]);
    }
  }

  async function loadOtherCalls(authToken, moduleId) {
    const data = await getOtherCalls(authToken, moduleId);
    const ordered = orderCallRecords(data.records || []);
    setOtherRecords(ordered);
  }

  async function doLogin() {
    if (!mentorNameInput.trim()) {
      Alert.alert("Mentor name is required");
      return;
    }
    if (!mentorPasswordInput.trim()) {
      Alert.alert("Password is required");
      return;
    }
    setLoading(true);
    try {
      const data = await login(mentorNameInput.trim(), mentorPasswordInput);
      setToken(data.token);
      setMentorName(data.mentor);
      await storeSession(data.token, data.mentor);
      const storedModuleRaw = await AsyncStorage.getItem(MODULE_KEY);
      const storedModule = storedModuleRaw ? Number(storedModuleRaw) : null;
      const modData = await getModules(data.token, storedModule || "");
      const moduleList = modData.modules || [];
      const pickedModule = modData.selected_module_id || (moduleList.length ? moduleList[0].module_id : null);
      setModules(moduleList);
      setSelectedModuleId(pickedModule || null);
      await storeSelectedModule(pickedModule || "");
      if (pickedModule) {
        await Promise.all([
          loadDashboard(data.token, pickedModule, null, false),
          loadResultDashboard(data.token, pickedModule, null),
          loadOtherCalls(data.token, pickedModule),
        ]);
      }
    } catch (err) {
      Alert.alert("Login failed", String(err.message || err));
    } finally {
      setLoading(false);
    }
  }

  async function loadDashboard(authToken, moduleId, preferredWeek = null, notifyIfNeeded = false) {
    const weekData = await getWeeks(authToken, moduleId);
    const allWeeks = weekData.weeks || [];
    const chosenWeek = preferredWeek || weekData.latest_week;
    setWeeks(allWeeks);
    setSelectedWeek(chosenWeek);
    await storeSelectedWeek(chosenWeek);
    if (!chosenWeek) {
      setRecords([]);
      setAllDone(false);
      setRetryRecords([]);
      await AsyncStorage.setItem(RETRY_COUNT_KEY, "0");
      return;
    }
    const callData = await getCalls(authToken, chosenWeek, moduleId);
    setRecords(orderCallRecords(callData.records || []));
    setAllDone(Boolean(callData.all_done));
    if (callData.all_done) {
      const retryData = await getRetryList(authToken, chosenWeek, moduleId);
      const retries = retryData.records || [];
      setRetryRecords(retries);
      if (notifyIfNeeded) {
        await maybeNotifyRetryPending(chosenWeek, retries.length);
      }
    } else {
      setRetryRecords([]);
      await AsyncStorage.setItem(RETRY_COUNT_KEY, "0");
    }
  }

  useEffect(() => {
    (async () => {
      await configureNotificationChannel();
      await ensureNotificationPermission();
      try {
        const savedTheme = await AsyncStorage.getItem(THEME_KEY);
        if (savedTheme === "light" || savedTheme === "dark" || savedTheme === "system") {
          setThemeMode(savedTheme);
        }
      } catch (_) {}
    })();
  }, []);

  useEffect(() => {
    if (selectedWeek) setWeekReportInput(String(selectedWeek));
  }, [selectedWeek]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const storedApiBase = (await AsyncStorage.getItem(API_BASE_URL_KEY)) || LIVE_API_BASE_URL;
        setApiBaseUrl(LIVE_API_BASE_URL);
        setApiBaseUrlState(LIVE_API_BASE_URL);
        if (storedApiBase !== LIVE_API_BASE_URL) {
          await storeApiBaseUrl(LIVE_API_BASE_URL);
        }
        const raw = await AsyncStorage.getItem(SESSION_KEY);
        const storedWeekRaw = await AsyncStorage.getItem(WEEK_KEY);
        const storedResultUploadRaw = await AsyncStorage.getItem(RESULT_UPLOAD_KEY);
        const storedModuleRaw = await AsyncStorage.getItem(MODULE_KEY);
        const storedWeek = storedWeekRaw ? Number(storedWeekRaw) : null;
        const storedResultUpload = storedResultUploadRaw ? Number(storedResultUploadRaw) : null;
        const storedModule = storedModuleRaw ? Number(storedModuleRaw) : null;
        if (!raw) {
          return;
        }
        const parsed = JSON.parse(raw);
        if (!parsed?.token) {
          await clearSession();
          return;
        }
        setToken(parsed.token);
        setMentorName(parsed.mentorName || "");
        const modData = await getModules(parsed.token, storedModule || "");
        const moduleList = modData.modules || [];
        const pickedModule = modData.selected_module_id || (moduleList.length ? moduleList[0].module_id : null);
        setModules(moduleList);
        setSelectedModuleId(pickedModule || null);
        await storeSelectedModule(pickedModule || "");
        if (pickedModule) {
          await loadDashboard(parsed.token, pickedModule, storedWeek, true);
          await loadResultDashboard(parsed.token, pickedModule, storedResultUpload);
          await loadOtherCalls(parsed.token, pickedModule);
        }
      } catch (err) {
        await clearSession();
      } finally {
        if (mounted) {
          setInitializing(false);
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!token || initializing || !selectedModuleId) {
      return;
    }
    let mounted = true;
    setLoading(true);
    Promise.all([
      loadDashboard(token, selectedModuleId, selectedWeek, true),
      loadResultDashboard(token, selectedModuleId, selectedResultUpload),
      loadOtherCalls(token, selectedModuleId),
    ])
      .catch(async () => {
        Alert.alert("Session expired", "Please login again.");
        try {
          await clearSession();
        } catch (_) {}
        if (mounted) {
          setToken("");
          setMentorName("");
          setMentorNameInput("");
        }
      })
      .finally(() => {
        if (mounted) {
          setLoading(false);
        }
      });
    return () => {
      mounted = false;
    };
  }, [token, initializing, selectedModuleId]);

  useEffect(() => {
    if (!token || !selectedModuleId) {
      return;
    }
    if (pollRef.current) {
      clearInterval(pollRef.current);
    }
    pollRef.current = setInterval(() => {
      Promise.all([
        selectedWeek ? loadDashboard(token, selectedModuleId, selectedWeek, true) : Promise.resolve(),
        loadResultDashboard(token, selectedModuleId, selectedResultUpload),
        loadOtherCalls(token, selectedModuleId),
      ]).catch(() => {});
    }, 12000);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
      }
    };
  }, [token, selectedModuleId, selectedWeek, selectedResultUpload]);

  useEffect(() => {
    const sub = AppState.addEventListener("change", (nextState) => {
      if (
        appState.current.match(/inactive|background/) &&
        nextState === "active" &&
        activeCall
      ) {
        const elapsedSec = Math.max(0, Math.round((Date.now() - callStart) / 1000));
        const autoMinutes = elapsedSec > 0 ? Math.max(1, Math.round(elapsedSec / 60)) : "";
        setDuration(String(autoMinutes));
        setModalVisible(true);
      }
      appState.current = nextState;
    });
    return () => sub.remove();
  }, [activeCall, callStart]);

  async function onSelectWeek(week) {
    if (!selectedModuleId) return;
    setLoading(true);
    try {
      await loadDashboard(token, selectedModuleId, week, false);
    } catch (err) {
      Alert.alert("Load failed", String(err.message || err));
    } finally {
      setLoading(false);
    }
  }

  async function onSelectResultUpload(uploadId) {
    if (!selectedModuleId) return;
    setLoading(true);
    try {
      await loadResultDashboard(token, selectedModuleId, uploadId);
    } catch (err) {
      Alert.alert("Load failed", String(err.message || err));
    } finally {
      setLoading(false);
    }
  }

  async function onSelectModule(moduleId) {
    if (!moduleId || moduleId === selectedModuleId) return;
    setLoading(true);
    try {
      setSelectedModuleId(moduleId);
      await storeSelectedModule(moduleId);
      await storeSelectedWeek("");
      await storeSelectedResultUpload("");
      setSelectedWeek(null);
      setSelectedResultUpload(null);
      await Promise.all([
        loadDashboard(token, moduleId, null, false),
        loadResultDashboard(token, moduleId, null),
        loadOtherCalls(token, moduleId),
      ]);
    } catch (err) {
      Alert.alert("Module switch failed", String(err.message || err));
    } finally {
      setLoading(false);
    }
  }

  function onSelectBottomTab(menuKey) {
    setActiveMenu(menuKey);
    const defaults = MENTOR_SUBMENUS[menuKey] || [{ key: "calls" }];
    setActiveSubmenu(defaults[0].key);
    if (menuKey === "attendance_calls") {
      setLastCallType("attendance");
    } else if (menuKey === "result_calls") {
      setLastCallType("result");
    } else if (menuKey === "other_calls") {
      setLastCallType("other");
    }
  }

  async function toggleThemeMode() {
    const next = isDark ? "light" : "dark";
    setThemeMode(next);
    try {
      await AsyncStorage.setItem(THEME_KEY, next);
    } catch (_) {}
  }

  async function onGenerateWeekReport() {
    const wk = Number(weekReportInput);
    if (!wk) {
      Alert.alert("Week required", "Enter a valid week number.");
      return;
    }
    await onSelectWeek(wk);
  }

  async function copyText(text, title = "Copied") {
    const value = String(text || "").trim();
    if (!value) {
      Alert.alert("Nothing to copy");
      return;
    }
    try {
      await Clipboard.setStringAsync(value);
      Alert.alert(title, "Copied to clipboard");
    } catch (_) {
      await Share.share({ message: value, title });
    }
  }

  function placeCall(record, target = "father") {
    let phone = "";
    if (activeMenu === "other_calls" && target === "student") {
      phone = (record.student.student_mobile || "").trim();
    } else {
      phone = (record.student.father_mobile || record.student.mother_mobile || "").trim();
    }
    if (!phone) {
      Alert.alert("Number not available");
      return;
    }
    setActiveCall({ ...record, call_target: target });
    setLastCallType(activeMenu === "result_calls" ? "result" : "attendance");
    if (activeMenu === "other_calls") {
      setLastCallType("other");
    }
    setCallStart(Date.now());
    if (activeMenu === "other_calls" && target === "student") {
      setTalked("student");
    } else {
      setTalked("father");
    }
    setDuration("");
    setRemark("");
    setCallReason("");
    Linking.openURL(`tel:${phone}`);
  }

  async function submitCall(status) {
    if (!activeCall) {
      return;
    }
    if ((lastCallType === "attendance" || lastCallType === "result") && status === "received" && !remark.trim()) {
      Alert.alert("Remark required", "Please enter parent remark for received calls.");
      return;
    }
    setLoading(true);
    try {
      const payload = {
        id: activeCall.call_id,
        module_id: selectedModuleId,
        status,
        talked,
        duration,
        reason: remark,
      };
      if (lastCallType === "result") {
        await saveResultCall(token, payload);
      } else if (lastCallType === "other") {
        await saveOtherCall(token, {
          id: activeCall.call_id,
          module_id: selectedModuleId,
          status,
          talked,
          duration,
          remark,
          call_reason: callReason,
          target: activeCall.call_target || "father",
        });
      } else {
        await saveCall(token, payload);
      }
      setModalVisible(false);
      setActiveCall(null);
      setRemark("");
      setDuration("");
      setCallReason("");
      if (lastCallType === "result") {
        await loadResultDashboard(token, selectedModuleId, selectedResultUpload);
      } else if (lastCallType === "other") {
        await loadOtherCalls(token, selectedModuleId);
      } else {
        await loadDashboard(token, selectedModuleId, selectedWeek, true);
      }
    } catch (err) {
      Alert.alert("Save failed", String(err.message || err));
    } finally {
      setLoading(false);
    }
  }

  async function onMarkMessage(callId) {
    setLoading(true);
    try {
      await markMessage(token, callId, selectedModuleId);
      await loadDashboard(token, selectedModuleId, selectedWeek, true);
    } catch (err) {
      Alert.alert("Failed", String(err.message || err));
    } finally {
      setLoading(false);
    }
  }

  async function onMarkResultMessage(callId) {
    setLoading(true);
    try {
      await markResultMessage(token, callId, selectedModuleId);
      await loadResultDashboard(token, selectedModuleId, selectedResultUpload);
    } catch (err) {
      Alert.alert("Failed", String(err.message || err));
    } finally {
      setLoading(false);
    }
  }

  async function onLogout() {
    try {
      if (token) {
        await logout(token);
      }
    } catch (_) {}
    await clearSession();
    if (typeof onExitApp === "function") {
      onExitApp();
      return;
    }
    setToken("");
    setMentorName("");
    setMentorNameInput("");
    setModules([]);
    setSelectedModuleId(null);
    setWeeks([]);
    setSelectedWeek(null);
    setRecords([]);
    setRetryRecords([]);
    setResultCycles([]);
    setSelectedResultUpload(null);
    setResultRecords([]);
    setResultRetryRecords([]);
    setResultReport("");
    setOtherRecords([]);
  }

  if (initializing) {
    return (
      <SafeAreaView style={[styles.page, { backgroundColor: palette.pageBg }]}>
        <StatusBar style={isDark ? "light" : "dark"} />
        <ActivityIndicator style={{ marginTop: 80 }} />
      </SafeAreaView>
    );
  }

  if (!token) {
    return (
      <SafeAreaView style={[styles.page, { backgroundColor: palette.pageBg }]}>
        <StatusBar style={isDark ? "light" : "dark"} />
        <View style={[styles.loginCard, { backgroundColor: palette.cardBg, borderColor: palette.cardBorder }]}>
          <Text style={[styles.title, { color: palette.headerText }]}>EasyMentor Mobile</Text>
          <Text style={[styles.subtitle, { color: palette.subText }]}>Mentor Login</Text>
          <Text style={styles.serverHint}>Server: {LIVE_API_BASE_URL}</Text>
          <TextInput
            style={styles.input}
            placeholder="Mentor short name"
            value={mentorNameInput}
            onChangeText={setMentorNameInput}
            autoCapitalize="none"
          />
          <TextInput
            style={styles.input}
            placeholder="Password"
            value={mentorPasswordInput}
            onChangeText={setMentorPasswordInput}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry={!showPassword}
          />
          <TouchableOpacity style={styles.weekButton} onPress={() => setShowPassword((v) => !v)}>
            <Text style={styles.weekButtonText}>{showPassword ? "Hide Password" : "Show Password"}</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.primaryButton} onPress={doLogin} disabled={loading}>
            <Text style={styles.primaryButtonText}>{loading ? "Please wait..." : "Login"}</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  return (
      <SafeAreaView style={[styles.page, { backgroundColor: palette.pageBg }]}>
      <StatusBar style={isDark ? "light" : "dark"} />
      <View style={[styles.header, { backgroundColor: palette.headerBg, borderColor: palette.cardBorder }]}>
        <View>
          <Text style={[styles.title, { color: palette.headerText }]}>{mentorName}</Text>
          <Text style={styles.moduleTag}>Module: {selectedModuleName}</Text>
          {activeMenu === "report" || activeSubmenu === "report" ? (
            <Text style={[styles.subtitle, { color: palette.subText }]}>
              {activeMenu === "report"
                ? (activeSubmenu === "result" ? `Result ${selectedResultUpload || "-"}` : activeSubmenu === "direct" ? "Direct Calls Summary" : `Week ${selectedWeek || "-"}`)
                : lastCallType === "result"
                ? `Result ${selectedResultUpload || "-"}`
                : `Week ${selectedWeek || "-"}`}
            </Text>
          ) : activeMenu === "message" ? (
            <Text style={[styles.subtitle, { color: palette.subText }]}>Open WhatsApp tools for parent communication</Text>
          ) : (
            <Text style={[styles.subtitle, { color: palette.subText }]}>
              Calls done: {visibleCompletedCount}/{visibleRecords.length}
            </Text>
          )}
        </View>
        <View style={styles.headerActions}>
          <TouchableOpacity style={styles.overflowButton} onPress={() => setHeaderMenuOpen(true)}>
            <Text style={styles.overflowButtonText}>⋮</Text>
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.weeksRow}>
        {modules.map((m) => (
          <TouchableOpacity
            key={m.module_id}
            onPress={() => onSelectModule(m.module_id)}
            style={[styles.weekButton, selectedModuleId === m.module_id && styles.weekButtonActive]}
          >
            <Text style={[styles.weekButtonText, selectedModuleId === m.module_id && styles.weekButtonTextActive]}>
              {m.variant} {m.semester}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {activeMenu === "attendance_calls" ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.weeksRow}>
          {weeks.map((week) => (
            <TouchableOpacity
              key={week}
              onPress={() => onSelectWeek(week)}
              style={[styles.weekButton, selectedWeek === week && styles.weekButtonActive]}
            >
              <Text style={[styles.weekButtonText, selectedWeek === week && styles.weekButtonTextActive]}>
                Week {week}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      ) : null}

      {activeMenu === "result_calls" ? (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.weeksRow}>
          {resultCycles.map((cycle) => (
            <TouchableOpacity
              key={cycle.upload_id}
              onPress={() => onSelectResultUpload(cycle.upload_id)}
              style={[
                styles.weekButton,
                selectedResultUpload === cycle.upload_id && styles.weekButtonActive,
              ]}
            >
              <Text
                style={[
                  styles.weekButtonText,
                  selectedResultUpload === cycle.upload_id && styles.weekButtonTextActive,
                ]}
              >
                {cycle.test_name}-{cycle.subject_name}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      ) : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.submenuRow}>
        {(MENTOR_SUBMENUS[activeMenu] || []).map((sub) => (
          <TouchableOpacity
            key={`${activeMenu}-${sub.key}`}
            onPress={() => setActiveSubmenu(sub.key)}
            style={[
              styles.submenuChip,
              { backgroundColor: palette.subMenuChipBg, borderColor: palette.subMenuChipBorder },
              activeSubmenu === sub.key && styles.submenuChipActive,
              activeSubmenu === sub.key && { backgroundColor: palette.subMenuChipActiveBg, borderColor: palette.subMenuChipActiveBg },
            ]}
          >
            <Text
              style={[
                styles.submenuChipText,
                { color: palette.subMenuChipText },
                activeSubmenu === sub.key && styles.submenuChipTextActive,
                activeSubmenu === sub.key && { color: palette.subMenuChipActiveText },
              ]}
            >
              {sub.label}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      {loading && <ActivityIndicator style={{ marginVertical: 8 }} />}

      {activeMenu === "message" ? (
        <ScrollView contentContainerStyle={{ paddingBottom: 150 }}>
              <View style={[styles.reportCard, { backgroundColor: palette.cardBg, borderColor: palette.cardBorder }]}>
            <Text style={styles.reportTitle}>Message to Mentees</Text>
            <Text style={styles.reportLine}>Use web WhatsApp panel for guided bulk messaging.</Text>
            <TextInput
              style={[styles.input, { minHeight: 90, textAlignVertical: "top" }]}
              multiline
              value={messageDraft}
              onChangeText={setMessageDraft}
            />
            <TouchableOpacity
              style={[styles.primaryButton, { marginBottom: 8 }]}
              onPress={() => Linking.openURL(`${LIVE_API_BASE_URL}/mentor-whatsapp/`)}
            >
              <Text style={styles.primaryButtonText}>Open Message Panel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.outlineButton}
              onPress={() => Linking.openURL(`https://wa.me/?text=${encodeURIComponent(messageDraft || "")}`)}
            >
              <Text style={styles.outlineButtonText}>Open WhatsApp Draft</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      ) : activeMenu === "report" || activeSubmenu === "report" || activeSubmenu === "summary" ? (
        <ScrollView contentContainerStyle={{ paddingBottom: 150 }}>
          {(activeMenu === "report" ? activeSubmenu : (activeSubmenu === "summary" ? "direct" : lastCallType === "result" ? "result" : "attendance")) === "result" ? (
            <View style={[styles.reportCard, { backgroundColor: palette.cardBg, borderColor: palette.cardBorder }]}>
              <Text style={styles.reportTitle}>Result Call Report</Text>
              <Text style={styles.reportMeta}>Upload {selectedResultUpload || "-"}</Text>
              <View style={styles.reportStatsGrid}>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Total Defaulters</Text><Text style={styles.reportStatValue}>{resultReportStats.total}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Calls Done</Text><Text style={styles.reportStatValue}>{resultReportStats.done}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Not Received</Text><Text style={styles.reportStatValue}>{resultReportStats.notReceived}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Pre-informed</Text><Text style={styles.reportStatValue}>{resultReportStats.preInformed}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Avg Duration</Text><Text style={styles.reportStatValue}>{resultReportStats.avgDuration}m</Text></View>
              </View>
              <TouchableOpacity style={styles.primaryButton} onPress={() => copyText(resultReportMessage, "Result report")}>
                <Text style={styles.primaryButtonText}>Copy WhatsApp Report</Text>
              </TouchableOpacity>
              <View style={styles.reportPreviewBox}><Text style={styles.reportPreviewText}>{resultReportMessage}</Text></View>
            </View>
          ) : (activeMenu === "report" ? activeSubmenu : (activeSubmenu === "summary" ? "direct" : lastCallType === "other" ? "direct" : "attendance")) === "direct" ? (
            <View style={[styles.reportCard, { backgroundColor: palette.cardBg, borderColor: palette.cardBorder }]}>
              <Text style={styles.reportTitle}>Direct Calls Report</Text>
              <View style={styles.reportStatsGrid}>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Total Defaulters</Text><Text style={styles.reportStatValue}>{otherRecords.length}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Calls Done</Text><Text style={styles.reportStatValue}>{otherCompletedCount}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Not Received</Text><Text style={styles.reportStatValue}>{otherRecords.filter((x) => x.final_status === "not_received").length}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Pre-informed</Text><Text style={styles.reportStatValue}>{otherRecords.filter((x) => x.final_status === "pre_informed").length}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Avg Duration</Text><Text style={styles.reportStatValue}>{Math.round((otherRecords.filter((x)=>x.final_status).reduce((a,x)=>a+Number(x.call_duration||x.duration_minutes||x.duration||0),0))/Math.max(1,otherRecords.filter((x)=>x.final_status).length))}m</Text></View>
              </View>
              <TouchableOpacity style={styles.primaryButton} onPress={() => copyText(directReportMessage, "Direct report")}>
                <Text style={styles.primaryButtonText}>Copy WhatsApp Report</Text>
              </TouchableOpacity>
              <View style={styles.reportPreviewBox}><Text style={styles.reportPreviewText}>{directReportMessage}</Text></View>
            </View>
          ) : (
            <View style={[styles.reportCard, { backgroundColor: palette.cardBg, borderColor: palette.cardBorder }]}>
              <Text style={styles.reportTitle}>Weekly Mentor Report</Text>
              <View style={{ flexDirection: "row", gap: 8, marginBottom: 8, alignItems: "center" }}>
                <TextInput
                  style={[styles.input, { flex: 1, marginBottom: 0 }]}
                  placeholder="Enter week number"
                  keyboardType="numeric"
                  value={weekReportInput}
                  onChangeText={setWeekReportInput}
                />
                <TouchableOpacity style={styles.weekButton} onPress={onGenerateWeekReport}>
                  <Text style={styles.weekButtonText}>Generate</Text>
                </TouchableOpacity>
              </View>
              <Text style={styles.reportMeta}>Week {selectedWeek || "-"}</Text>
              <View style={styles.reportStatsGrid}>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Total Defaulters</Text><Text style={styles.reportStatValue}>{reportStats.total}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Calls Done</Text><Text style={styles.reportStatValue}>{reportStats.done}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Not Received</Text><Text style={styles.reportStatValue}>{reportStats.notReceived}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Pre-informed</Text><Text style={styles.reportStatValue}>{reportStats.preInformed}</Text></View>
                <View style={styles.reportStatCard}><Text style={styles.reportStatLabel}>Avg Duration</Text><Text style={styles.reportStatValue}>{reportStats.avgDuration}m</Text></View>
              </View>
              <TouchableOpacity style={styles.primaryButton} onPress={() => copyText(attendanceReportMessage, "Attendance report")}>
                <Text style={styles.primaryButtonText}>Copy WhatsApp Report</Text>
              </TouchableOpacity>
              <View style={styles.reportPreviewBox}><Text style={styles.reportPreviewText}>{attendanceReportMessage}</Text></View>
            </View>
          )}
        </ScrollView>
      ) : activeSubmenu === "retry" ? (
        <ScrollView contentContainerStyle={{ paddingBottom: 150 }}>
            <View style={[styles.reportCard, { backgroundColor: palette.cardBg, borderColor: palette.cardBorder }]}>
            <Text style={styles.reportTitle}>
              {activeMenu === "result_calls" ? "Result Retry List" : "Attendance Retry List"}
            </Text>
            {(activeMenu === "result_calls" ? resultRetryRecords : retryRecords).length === 0 ? (
              <Text style={styles.reportLine}>
                {activeMenu === "result_calls"
                  ? "No retry records. Complete result calls first."
                  : "No retry records. Complete attendance calls first."}
              </Text>
            ) : (
              (activeMenu === "result_calls" ? resultRetryRecords : retryRecords).map((r) => {
                const phone = r.father_mobile || r.mother_mobile;
                const message =
                  activeMenu === "result_calls"
                    ? `Dear Parent, your ward ${r.student_name} (Roll ${r.roll_no}) is failed. ${r.fail_reason}.`
                    : `Dear Parent, your ward ${r.student_name} (Roll ${r.roll_no}) attendance is below 80%. Weekly: ${r.week_percentage}. Overall: ${r.overall_percentage}.`;
                const wa = `https://wa.me/${phone}?text=${encodeURIComponent(message)}`;
                return (
                  <View key={r.call_id} style={styles.retryRow}>
                    <Text style={styles.retryText}>
                      {r.roll_no} {r.student_name}
                    </Text>
                    <View style={styles.retryActions}>
                      <TouchableOpacity style={styles.smallButton} onPress={() => Linking.openURL(`tel:${phone}`)}>
                        <Text style={styles.smallButtonText}>Call</Text>
                      </TouchableOpacity>
                      <TouchableOpacity style={styles.smallButton} onPress={() => Linking.openURL(wa)}>
                        <Text style={styles.smallButtonText}>WhatsApp</Text>
                      </TouchableOpacity>
                      {!r.message_sent ? (
                        <TouchableOpacity
                          style={styles.smallButton}
                          onPress={() =>
                            activeMenu === "result_calls"
                              ? onMarkResultMessage(r.call_id)
                              : onMarkMessage(r.call_id)
                          }
                        >
                          <Text style={styles.smallButtonText}>Mark Sent</Text>
                        </TouchableOpacity>
                      ) : (
                        <Text style={styles.sentText}>Sent</Text>
                      )}
                    </View>
                  </View>
                );
              })
            )}
          </View>
        </ScrollView>
      ) : (
        <FlatList
          data={visibleRecords}
          keyExtractor={(item) => String(item.call_id)}
          contentContainerStyle={{ paddingBottom: 150 }}
          renderItem={({ item }) => {
            const finalStatus = item.final_status || "pending";
            const isReceived = finalStatus === "received";
            const isNotReceived = finalStatus === "not_received";

            let actionLabel = "Call Parent";
            let actionStyle = styles.primaryButton;
            if (isReceived) {
              actionLabel = "Call Done";
              actionStyle = styles.doneButton;
            } else if (isNotReceived) {
              actionLabel = "Call Not Received";
              actionStyle = styles.notReceivedButton;
            }

            return (
              <View style={[styles.card, { backgroundColor: palette.cardBg, borderColor: palette.cardBorder }]}>
                <Text style={styles.cardTitle}>{item.student.name}</Text>
                <Text style={styles.cardMeta}>Enrollment: {item.student.enrollment || "-"}</Text>
                <View style={styles.metricGrid}>
                  <View style={styles.metricCell}>
                    <Text style={styles.metricLabel}>Weekly</Text>
                    <Text style={styles.metricValue}>{item.week_percentage ?? "-"}</Text>
                  </View>
                  <View style={styles.metricCell}>
                    <Text style={styles.metricLabel}>Overall</Text>
                    <Text style={styles.metricValue}>{item.overall_percentage ?? "-"}</Text>
                  </View>
                </View>
                {activeMenu === "other_calls" ? (
                  <Text style={styles.cardMeta}>
                    Last target: {item.last_called_target || "-"} | Reason: {item.call_done_reason || "-"}
                  </Text>
                ) : null}
                {activeMenu === "result_calls" ? (
                  <Text style={styles.cardMeta}>
                    {item.test_name} | {item.subject_name} | {item.marks_current ?? "-"}/{item.marks_total ?? "-"}
                  </Text>
                ) : null}
                <View style={styles.badgeRow}>
                  {activeMenu === "result_calls" && item.fail_reason ? (
                    <View style={[styles.badgePill, styles.badgeDanger]}>
                      <Text style={styles.badgeText}>Rule Violation</Text>
                    </View>
                  ) : null}
                  <View
                    style={[
                      styles.badgePill,
                      finalStatus === "received"
                        ? styles.badgeSuccess
                        : finalStatus === "not_received"
                        ? styles.badgeWaiting
                        : finalStatus === "pre_informed"
                        ? styles.badgeNeutral
                        : styles.badgePrimary,
                    ]}
                  >
                    <Text style={styles.badgeText}>{statusBadgeStyle(finalStatus).text}</Text>
                  </View>
                </View>
                {activeMenu === "other_calls" ? (
                  <View style={styles.otherActions}>
                    <TouchableOpacity
                      style={styles.primaryButton}
                      onPress={() => placeCall(item, "student")}
                      disabled={isReceived}
                    >
                      <Text style={styles.primaryButtonText}>Call Student</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      style={actionStyle}
                      onPress={() => placeCall(item, "father")}
                      disabled={isReceived}
                    >
                      <Text style={styles.primaryButtonText}>Call Father</Text>
                    </TouchableOpacity>
                  </View>
                ) : (
                  <TouchableOpacity
                    style={actionStyle}
                    onPress={() => placeCall(item)}
                    disabled={isReceived}
                  >
                    <Text style={styles.primaryButtonText}>{actionLabel}</Text>
                  </TouchableOpacity>
                )}
              </View>
            );
          }}
          ListEmptyComponent={<Text style={styles.empty}>No calls for selected menu.</Text>}
        />
      )}

      <View style={[styles.bottomTabBar, { backgroundColor: palette.bottomBarBg, borderColor: palette.bottomBarBorder }]}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingRight: 18 }}>
          {MENU_ITEMS.map((item) => (
            <TouchableOpacity
              key={item.key}
              style={[
                styles.bottomTabButton,
                activeMenu === item.key && styles.bottomTabButtonActive,
                activeMenu === item.key && { backgroundColor: palette.tabActiveBg },
              ]}
              onPress={() => onSelectBottomTab(item.key)}
            >
              <Text
                style={[
                  styles.bottomTabText,
                  { color: palette.tabText },
                  activeMenu === item.key && styles.bottomTabTextActive,
                  activeMenu === item.key && { color: palette.tabActiveText },
                ]}
              >
                {item.label}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
        <Text style={[styles.moreHint, { color: palette.tabText }]}>›</Text>
      </View>

      <Modal
        visible={headerMenuOpen}
        animationType="fade"
        transparent
        onRequestClose={() => setHeaderMenuOpen(false)}
      >
        <View style={styles.headerMenuOverlay}>
          <TouchableOpacity style={styles.headerMenuBackdrop} onPress={() => setHeaderMenuOpen(false)} />
          <View style={styles.headerMenuCard}>
            <TouchableOpacity
              style={styles.headerMenuItem}
              onPress={() => {
                setHeaderMenuOpen(false);
                toggleThemeMode();
              }}
            >
              <Text style={styles.headerMenuItemText}>{isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.headerMenuItem}
              onPress={() => {
                setHeaderMenuOpen(false);
                onLogout();
              }}
            >
              <Text style={[styles.headerMenuItemText, { color: COLOR_SYSTEM.danger }]}>Logout</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      <Modal
        visible={modalVisible}
        animationType="slide"
        transparent
        onRequestClose={() => setModalVisible(false)}
      >
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Call Result</Text>
            {activeCall ? (
              <Text style={styles.modalMeta}>
                {activeCall.student.roll_no || "-"} | {activeCall.student.name}
              </Text>
            ) : null}
            <Text style={styles.modalLabel}>Talked With</Text>
            <View style={styles.choiceRow}>
              {talkedChoiceOptions.map((opt) => (
                <TouchableOpacity
                  key={opt}
                  style={[styles.choiceButton, talked === opt && styles.choiceButtonActive]}
                  onPress={() => setTalked(opt)}
                >
                  <Text style={[styles.choiceText, talked === opt && styles.choiceTextActive]}>
                    {opt}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <Text style={styles.modalLabel}>Duration (minutes)</Text>
            <TextInput
              style={styles.input}
              keyboardType="numeric"
              value={duration}
              onChangeText={setDuration}
            />

            <Text style={styles.modalLabel}>
              {lastCallType === "other" ? "Parents Remark" : "Parent Remark"}
            </Text>
            <TextInput style={styles.input} value={remark} onChangeText={setRemark} />
            {lastCallType === "other" ? (
              <>
                <Text style={styles.modalLabel}>Call Done Reason</Text>
                <TextInput style={styles.input} value={callReason} onChangeText={setCallReason} />
              </>
            ) : null}

            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.secondaryButton}
                onPress={() => submitCall("not_received")}
              >
                <Text style={styles.secondaryButtonText}>Not Received</Text>
              </TouchableOpacity>
              <TouchableOpacity style={styles.primaryButton} onPress={() => submitCall("received")}>
                <Text style={styles.primaryButtonText}>Received</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  page: {
    flex: 1,
    backgroundColor: COLOR_SYSTEM.background,
    paddingHorizontal: DS.s16,
    paddingTop: Platform.OS === "android" ? (RNStatusBar.currentHeight || DS.s8) : DS.s8,
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: DS.s16,
    backgroundColor: "#ffffff",
    borderRadius: DS.radiusCard,
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    padding: DS.s16,
  },
  headerActions: {
    flexDirection: "row",
    gap: DS.s8,
  },
  overflowButton: {
    width: 40,
    height: 40,
    borderRadius: DS.radiusBtn,
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#ffffff",
  },
  overflowButtonText: {
    fontSize: 20,
    lineHeight: 22,
    color: COLOR_SYSTEM.textPrimary,
    fontWeight: "700",
  },
  title: {
    fontSize: 22,
    lineHeight: 28,
    fontWeight: "700",
    color: COLOR_SYSTEM.textPrimary,
  },
  subtitle: {
    color: COLOR_SYSTEM.textSecondary,
    marginTop: 2,
    fontSize: 14,
  },
  moduleTag: {
    color: COLOR_SYSTEM.neutral,
    marginTop: 2,
    fontSize: 12,
  },
  serverHint: {
    color: "#6b7f95",
    fontSize: 12,
    marginBottom: 8,
  },
  loginCard: {
    marginTop: 120,
    backgroundColor: "#ffffff",
    borderRadius: 14,
    padding: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.1,
    shadowRadius: 10,
    elevation: 4,
  },
  input: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    borderRadius: DS.radiusInput,
    paddingVertical: 12,
    paddingHorizontal: 12,
    marginTop: DS.s8,
    marginBottom: DS.s16,
    fontSize: 16,
  },
  primaryButton: {
    backgroundColor: COLOR_SYSTEM.primary,
    borderRadius: DS.radiusBtn,
    minHeight: 48,
    paddingVertical: 12,
    paddingHorizontal: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryButtonText: {
    color: "#fff",
    fontWeight: "700",
    fontSize: 16,
  },
  outlineButton: {
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.primary,
    borderRadius: DS.radiusBtn,
    paddingVertical: 8,
    paddingHorizontal: 10,
  },
  outlineButtonText: {
    color: COLOR_SYSTEM.primary,
    fontWeight: "600",
  },
  weeksRow: {
    minHeight: 46,
    marginBottom: 8,
  },
  submenuRow: {
    minHeight: 44,
    marginBottom: 8,
  },
  submenuChip: {
    borderWidth: 1,
    borderColor: "#c9d7e8",
    borderRadius: 8,
    paddingVertical: 7,
    paddingHorizontal: 11,
    marginRight: 8,
    backgroundColor: "#fff",
  },
  submenuChipActive: {
    backgroundColor: "#0f3057",
    borderColor: "#0f3057",
  },
  submenuChipText: {
    color: "#123555",
    fontWeight: "700",
    fontSize: 12,
  },
  submenuChipTextActive: {
    color: "#fff",
  },
  weekButton: {
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    borderRadius: DS.radiusBtn,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginRight: 8,
    backgroundColor: "#fff",
  },
  weekButtonActive: {
    backgroundColor: "#0f3057",
    borderColor: "#0f3057",
  },
  weekButtonText: {
    color: COLOR_SYSTEM.textPrimary,
    fontWeight: "600",
    fontSize: 14,
  },
  weekButtonTextActive: {
    color: "#fff",
  },
  card: {
    backgroundColor: "#fff",
    borderRadius: DS.radiusCard,
    padding: DS.s16,
    marginBottom: DS.s16,
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    shadowColor: "#0f172a",
    shadowOpacity: 0.08,
    shadowOffset: { width: 0, height: 4 },
    shadowRadius: 12,
    elevation: 2,
  },
  cardTitle: {
    color: COLOR_SYSTEM.textPrimary,
    fontWeight: "700",
    marginBottom: 4,
    fontSize: 18,
    lineHeight: 24,
  },
  cardMeta: {
    color: COLOR_SYSTEM.neutral,
    marginBottom: 6,
    fontSize: 14,
    lineHeight: 20,
  },
  metricGrid: {
    flexDirection: "row",
    gap: DS.s8,
    marginBottom: DS.s8,
  },
  metricCell: {
    flex: 1,
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    borderRadius: DS.radiusBtn,
    paddingVertical: 10,
    paddingHorizontal: 12,
    backgroundColor: "#f8fbff",
  },
  metricLabel: {
    color: COLOR_SYSTEM.neutral,
    fontSize: 12,
  },
  metricValue: {
    color: COLOR_SYSTEM.textPrimary,
    fontWeight: "700",
    fontSize: 16,
    marginTop: 2,
  },
  badgeRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: DS.s8,
    marginBottom: DS.s16,
  },
  badgePill: {
    borderRadius: 999,
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  badgePrimary: {
    backgroundColor: COLOR_SYSTEM.primary,
  },
  badgeSuccess: {
    backgroundColor: COLOR_SYSTEM.success,
  },
  badgeWaiting: {
    backgroundColor: COLOR_SYSTEM.waiting,
  },
  badgeDanger: {
    backgroundColor: COLOR_SYSTEM.danger,
  },
  badgeNeutral: {
    backgroundColor: COLOR_SYSTEM.neutral,
  },
  badgeText: {
    color: "#fff",
    fontSize: 12,
    fontWeight: "700",
  },
  otherActions: {
    flexDirection: "row",
    gap: 8,
  },
  empty: {
    color: "#4f6680",
    textAlign: "center",
    marginTop: 30,
  },
  reportCard: {
    backgroundColor: "#fff",
    borderRadius: DS.radiusCard,
    padding: DS.s16,
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    shadowColor: "#0f172a",
    shadowOpacity: 0.08,
    shadowOffset: { width: 0, height: 4 },
    shadowRadius: 12,
    elevation: 2,
  },
  reportTitle: {
    color: COLOR_SYSTEM.textPrimary,
    fontWeight: "700",
    fontSize: 18,
    marginBottom: 8,
  },
  reportMeta: {
    color: COLOR_SYSTEM.neutral,
    marginBottom: 10,
    fontSize: 14,
  },
  reportLine: {
    color: COLOR_SYSTEM.textSecondary,
    marginBottom: 7,
    fontSize: 16,
    lineHeight: 22,
  },
  reportBody: {
    color: "#2f4761",
    marginTop: 10,
    lineHeight: 20,
  },
  reportStatsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
    marginBottom: DS.s16,
    gap: DS.s8,
  },
  reportStatCard: {
    width: "48%",
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    borderRadius: DS.radiusBtn,
    paddingVertical: 10,
    paddingHorizontal: 12,
    backgroundColor: "#f8fbff",
  },
  reportStatLabel: {
    color: COLOR_SYSTEM.neutral,
    fontSize: 12,
  },
  reportStatValue: {
    color: COLOR_SYSTEM.textPrimary,
    fontSize: 18,
    fontWeight: "700",
    marginTop: 2,
  },
  reportPreviewBox: {
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    borderRadius: DS.radiusBtn,
    padding: 12,
    marginTop: DS.s16,
    backgroundColor: "#f8fbff",
  },
  reportPreviewText: {
    color: COLOR_SYSTEM.textSecondary,
    fontSize: 14,
    lineHeight: 20,
  },
  retryBox: {
    position: "absolute",
    left: 12,
    right: 12,
    bottom: 10,
    backgroundColor: "#fff6e8",
    borderWidth: 1,
    borderColor: "#edcd95",
    borderRadius: 12,
    padding: 10,
  },
  retryTitle: {
    fontWeight: "700",
    color: "#664114",
    marginBottom: 6,
  },
  retryRow: {
    borderTopWidth: 1,
    borderTopColor: "#efd9b6",
    paddingVertical: 6,
  },
  retryText: {
    color: "#4a3113",
    marginBottom: 5,
  },
  retryActions: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
  },
  smallButton: {
    backgroundColor: "#b8741a",
    borderRadius: 7,
    paddingHorizontal: 10,
    paddingVertical: 7,
    marginRight: 6,
    marginBottom: 4,
  },
  smallButtonText: {
    color: "#fff",
    fontWeight: "600",
    fontSize: 12,
  },
  sentText: {
    color: "#1d7f4e",
    fontWeight: "700",
  },
  modalBg: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0,0,0,0.35)",
  },
  modalCard: {
    backgroundColor: "#fff",
    borderTopLeftRadius: 14,
    borderTopRightRadius: 14,
    padding: 16,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: "700",
    color: "#0f3057",
  },
  modalMeta: {
    color: "#3f5873",
    marginTop: 4,
    marginBottom: 10,
  },
  modalLabel: {
    color: "#2f4761",
    fontWeight: "600",
    marginTop: 4,
  },
  choiceRow: {
    flexDirection: "row",
    marginVertical: 8,
  },
  choiceButton: {
    borderWidth: 1,
    borderColor: "#b8c6da",
    borderRadius: 8,
    paddingVertical: 8,
    paddingHorizontal: 10,
    marginRight: 8,
  },
  choiceButtonActive: {
    borderColor: "#0f5e9c",
    backgroundColor: "#e7f3ff",
  },
  choiceText: {
    color: "#2f4761",
  },
  choiceTextActive: {
    color: "#0f5e9c",
    fontWeight: "700",
  },
  modalActions: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 8,
  },
  secondaryButton: {
    backgroundColor: "#a54a4a",
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 14,
    alignItems: "center",
    minWidth: 130,
  },
  secondaryButtonText: {
    color: "#fff",
    fontWeight: "600",
  },
  bottomTabBar: {
    position: "absolute",
    left: DS.s16,
    right: DS.s16,
    bottom: DS.s16,
    backgroundColor: "#ffffff",
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    borderRadius: DS.radiusCard,
    padding: DS.s8,
    flexDirection: "row",
    alignItems: "center",
    shadowColor: "#0f172a",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.12,
    shadowRadius: 8,
    elevation: 2,
  },
  headerMenuOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.25)",
    justifyContent: "flex-start",
    alignItems: "flex-end",
    paddingTop: Platform.OS === "android" ? (RNStatusBar.currentHeight || DS.s16) + 68 : 86,
    paddingRight: DS.s16,
  },
  headerMenuBackdrop: {
    ...StyleSheet.absoluteFillObject,
  },
  headerMenuCard: {
    minWidth: 220,
    borderWidth: 1,
    borderColor: COLOR_SYSTEM.border,
    borderRadius: DS.radiusCard,
    backgroundColor: "#ffffff",
    shadowColor: "#0f172a",
    shadowOpacity: 0.12,
    shadowOffset: { width: 0, height: 4 },
    shadowRadius: 10,
    elevation: 3,
    overflow: "hidden",
  },
  headerMenuItem: {
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#eef2f7",
  },
  headerMenuItemText: {
    color: COLOR_SYSTEM.textPrimary,
    fontSize: 16,
    fontWeight: "600",
  },
  bottomTabButton: {
    minWidth: 110,
    borderRadius: DS.radiusBtn,
    paddingVertical: 12,
    paddingHorizontal: 14,
    alignItems: "center",
    marginRight: 8,
  },
  bottomTabButtonActive: {
    backgroundColor: "#0f3057",
  },
  bottomTabText: {
    color: COLOR_SYSTEM.textSecondary,
    fontSize: 14,
    fontWeight: "700",
  },
  moreHint: {
    position: "absolute",
    right: 8,
    fontSize: 18,
    fontWeight: "700",
  },
  bottomTabTextActive: {
    color: "#fff",
  },
  menuOverlay: {
    flex: 1,
    flexDirection: "row",
    backgroundColor: "rgba(0,0,0,0.25)",
  },
  menuBackdrop: {
    flex: 1,
  },
  menuDrawer: {
    width: 260,
    backgroundColor: "#fff",
    paddingTop: 40,
    paddingHorizontal: 14,
    borderRightWidth: 1,
    borderRightColor: "#d9dfeb",
  },
  menuTitle: {
    fontSize: 18,
    fontWeight: "700",
    color: "#0f3057",
    marginBottom: 12,
  },
  menuItem: {
    borderWidth: 1,
    borderColor: "#d9dfeb",
    borderRadius: 8,
    paddingVertical: 11,
    paddingHorizontal: 12,
    marginBottom: 9,
    backgroundColor: "#fff",
  },
  menuItemActive: {
    borderColor: "#0f5e9c",
    backgroundColor: "#e7f3ff",
  },
  menuItemText: {
    color: "#2f4761",
    fontWeight: "600",
  },
  menuItemTextActive: {
    color: "#0f5e9c",
  },
  doneButton: {
    backgroundColor: COLOR_SYSTEM.success,
    borderRadius: DS.radiusBtn,
    minHeight: 48,
    paddingVertical: 12,
    paddingHorizontal: 14,
    alignItems: "center",
    opacity: 0.9,
  },
  notReceivedButton: {
    backgroundColor: COLOR_SYSTEM.waiting,
    borderRadius: DS.radiusBtn,
    minHeight: 48,
    paddingVertical: 12,
    paddingHorizontal: 14,
    alignItems: "center",
  },
});

