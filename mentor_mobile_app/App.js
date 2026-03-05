import React, { useEffect, useMemo, useState } from "react";
import {
  SafeAreaView,
  StatusBar,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  TextInput,
  Platform,
  FlatList,
  Alert,
  ActivityIndicator,
  Image,
  ScrollView,
  Modal,
  useColorScheme,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Clipboard from "expo-clipboard";
import { WebView } from "react-native-webview";
import * as DocumentPicker from "expo-document-picker";
import LegacyMentorApp from "./src/mentor/LegacyMentorApp";
import { LIVE_API_BASE_URL } from "./src/constants";
import {
  login,
  createStaffModule,
  getStaffAttendance,
  getStaffAttendanceReport,
  getStaffControlSummary,
  getStaffHomeSummary,
  getStaffModules,
  getStaffModulesManage,
  getStaffSubjects,
  getStaffResultReport,
  getStaffResultCycles,
  getStaffResultRows,
  getStaffStudents,
  getStaffWeeks,
  staffLogin,
  toggleStaffModule,
  setApiBaseUrl,
} from "./src/api";

const ROLE_KEY = "easymentor_mobile_role_v1";
const LEGACY_MENTOR_BASE_KEY = "easymentor_api_base_url_v1";
const STAFF_SESSION_KEY = "easymentor_mobile_staff_session_v1";
const MENTOR_SESSION_KEY = "easymentor_session_v1";
const PAGE_SIZE = 40;
const MOBILE_THEME_KEY = "easymentor_mobile_theme_v1";

const APP_COLORS = {
  bg: "#F7F9FC",
  card: "#ffffff",
  primary: "#2563eb",
  primaryDark: "#1e40af",
  accent: "#2563eb",
  success: "#16a34a",
  waiting: "#f59e0b",
  danger: "#dc2626",
  text: "#0f172a",
  muted: "#64748b",
  border: "#d7dfeb",
};

const APP_DS = {
  s8: 8,
  s16: 16,
  s24: 24,
  s32: 32,
  radiusCard: 16,
  radiusBtn: 12,
  radiusInput: 12,
};

const COORDINATOR_TABS = [
  { key: "attendance", label: "Attendance", path: "/view-attendance/" },
  { key: "results", label: "Result", path: "/view-results/" },
  { key: "students", label: "Student", path: "/upload-students/" },
  { key: "control", label: "Other", path: "/control-panel/" },
  { key: "settings", label: "More", path: "" },
];

const SUPERADMIN_TABS = [
  { key: "home", label: "Home", path: "/home/" },
  { key: "modules", label: "Modules", path: "/modules/" },
  { key: "students", label: "Students", path: "/upload-students/" },
  { key: "control", label: "Control", path: "/control-panel/" },
  { key: "settings", label: "Settings", path: "" },
];

const TAB_SUBMENUS = {
  home: [
    { key: "native", label: "Native" },
    { key: "home_web", label: "Home", path: "/home/" },
  ],
  modules: [
    { key: "native", label: "Native" },
    { key: "modules_web", label: "Manage Modules", path: "/modules/" },
  ],
  students: [
    { key: "native", label: "Native" },
    { key: "student_master", label: "Student Master", path: "/upload-students/" },
    { key: "manage_mentors", label: "Manage Mentor", path: "/manage-mentors/" },
  ],
  attendance: [
    { key: "native", label: "Native" },
    { key: "view_att", label: "View Attendance", path: "/view-attendance/" },
    { key: "upload_att", label: "Upload Attendance", path: "/upload-attendance/" },
    { key: "att_report", label: "Attendance Reports", path: "/reports/" },
    { key: "semester_register", label: "Semester Register", path: "/semester-register/" },
    { key: "delete_att", label: "Delete Attendance", path: "/delete-week/" },
  ],
  results: [
    { key: "native", label: "Native" },
    { key: "manage_subjects", label: "Manage Subjects", path: "/subjects/" },
    { key: "upload_th", label: "Upload TH Results", path: "/upload-results/" },
    { key: "view_th", label: "View TH Result", path: "/view-results/" },
    { key: "view_pr", label: "Upload/View PR Result", path: "/view-practical-marks/" },
    { key: "sif_marks", label: "SIF Marks Filling", path: "/sif-marks-template/" },
    { key: "delete_results", label: "Delete Results", path: "/delete-results/" },
    { key: "result_report", label: "Result Reports", path: "/result-reports/" },
  ],
  control: [
    { key: "native", label: "Native" },
    { key: "control_web", label: "Control Panel", path: "/control-panel/" },
    { key: "live_followup", label: "Live Followup Sheet", path: "/live-followup-sheet/" },
  ],
  settings: [
    { key: "native", label: "Settings" },
    { key: "upload_students_web", label: "Student Master", path: "/upload-students/" },
    { key: "control_web", label: "Control Panel", path: "/control-panel/" },
  ],
};

const APP_THEME = {
  light: {
    pageBg: "#F7F9FC",
    headerBg: "#1e40af",
    headerText: "#ffffff",
    headerSub: "#dbeafe",
    submenuBg: "#f8fbff",
    submenuBorder: "#d7dfeb",
    chipBg: "#ffffff",
    chipBorder: "#d7dfeb",
    chipText: "#334155",
    chipActiveBg: "#2563eb",
    chipActiveText: "#ffffff",
    tabBarBg: "#ffffff",
    tabBarBorder: "#d7dfeb",
    tabActiveBg: "#dbeafe",
    tabText: "#64748b",
    tabActiveText: "#1e40af",
  },
  dark: {
    pageBg: "#0b1220",
    headerBg: "#041224",
    headerText: "#f3f8ff",
    headerSub: "#bfdbfe",
    submenuBg: "#111827",
    submenuBorder: "#1b3458",
    chipBg: "#1e293b",
    chipBorder: "#334155",
    chipText: "#bfdbfe",
    chipActiveBg: "#1d4ed8",
    chipActiveText: "#ffffff",
    tabBarBg: "#0f172a",
    tabBarBorder: "#334155",
    tabActiveBg: "#1d4ed8",
    tabText: "#dbeafe",
    tabActiveText: "#ffffff",
  },
};

function UnifiedLoginScreen({ loading, username, password, onUsername, onPassword, onLogin }) {
  const [showPassword, setShowPassword] = useState(false);
  return (
    <SafeAreaView style={styles.gatewayPage}>
      <StatusBar barStyle="light-content" backgroundColor={APP_COLORS.primary} />
      <ScrollView contentContainerStyle={{ paddingBottom: 24 }} keyboardShouldPersistTaps="handled">
        <View style={styles.splashCard}>
          <Image source={{ uri: "https://easymentor-web.onrender.com/static/logo.png" }} style={styles.splashLogo} />
          <Text style={styles.splashTitle}>EasyMentor Mobile</Text>
          <Text style={styles.splashSub}>LJ Attendance Follow-up ERP</Text>
        </View>

        <View style={styles.gatewayCard}>
          <Text style={styles.gatewaySection}>Login</Text>
          <TextInput
            style={styles.serverInput}
            placeholder="Username (mentor/coordinator/superadmin)"
            autoCapitalize="none"
            autoCorrect={false}
            value={username}
            onChangeText={onUsername}
          />
          <TextInput
            style={[styles.serverInput, { marginTop: 8 }]}
            placeholder="Password"
            secureTextEntry={!showPassword}
            autoCapitalize="none"
            autoCorrect={false}
            value={password}
            onChangeText={onPassword}
          />
          <TouchableOpacity
            style={[styles.syncBtn, { alignSelf: "flex-start", marginTop: 8, marginLeft: 0 }]}
            onPress={() => setShowPassword((v) => !v)}
          >
            <Text style={styles.syncBtnText}>{showPassword ? "Hide Password" : "Show Password"}</Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.applyBtn} onPress={onLogin} disabled={loading}>
            {loading ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.applyBtnText}>Login</Text>}
          </TouchableOpacity>
        </View>

        <View style={styles.gatewayCard}>
          <Text style={styles.gatewaySection}>Why EasyMentor</Text>
          <Text style={styles.featureBullet}>- Faster call follow-up with fewer manual steps</Text>
          <Text style={styles.featureBullet}>- Attendance and result tracking from one app</Text>
          <Text style={styles.featureBullet}>- Better documentation with lower error risk</Text>
          <Text style={styles.featureBullet}>- Print-ready SIF support from live call records</Text>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function RoleWebTabsApp({ role, apiBaseUrl, onChangeBase, onExit }) {
  const systemIsDark = useColorScheme() === "dark";
  const [themeMode, setThemeMode] = useState("system");
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false);
  const isDark = themeMode === "system" ? systemIsDark : themeMode === "dark";
  const palette = isDark ? APP_THEME.dark : APP_THEME.light;
  const roleTabs = role === "superadmin" ? SUPERADMIN_TABS : COORDINATOR_TABS;
  const [activeTab, setActiveTab] = useState(roleTabs[0].key);
  const [submenuByTab, setSubmenuByTab] = useState({});
  const [currentUrl, setCurrentUrl] = useState(apiBaseUrl);
  const [reloadKey, setReloadKey] = useState(1);
  const [staffToken, setStaffToken] = useState("");
  const [staffUser, setStaffUser] = useState("");
  const [staffPass, setStaffPass] = useState("");
  const [staffModules, setStaffModules] = useState([]);
  const [staffModuleId, setStaffModuleId] = useState(null);
  const [staffStudents, setStaffStudents] = useState([]);
  const [staffWeeks, setStaffWeeks] = useState([]);
  const [staffWeek, setStaffWeek] = useState(null);
  const [staffAttendanceRows, setStaffAttendanceRows] = useState([]);
  const [staffResultCycles, setStaffResultCycles] = useState([]);
  const [staffResultUploadId, setStaffResultUploadId] = useState(null);
  const [staffResultRows, setStaffResultRows] = useState([]);
  const [staffResultMeta, setStaffResultMeta] = useState(null);
  const [staffSubjects, setStaffSubjects] = useState([]);
  const [resultUploadTest, setResultUploadTest] = useState("T1");
  const [resultUploadSubjectId, setResultUploadSubjectId] = useState("");
  const [resultUploadMode, setResultUploadMode] = useState("subject");
  const [resultUploadFile, setResultUploadFile] = useState(null);
  const [resultUploadMsg, setResultUploadMsg] = useState("");
  const [resultFilter, setResultFilter] = useState("either");
  const [staffControl, setStaffControl] = useState({ week: null, attendance: [], result: [], result_upload: null });
  const [staffHomeStats, setStaffHomeStats] = useState(null);
  const [staffHomeModules, setStaffHomeModules] = useState([]);
  const [staffManageModules, setStaffManageModules] = useState([]);
  const [newModuleName, setNewModuleName] = useState("");
  const [newModuleBatch, setNewModuleBatch] = useState("");
  const [newModuleYear, setNewModuleYear] = useState("FY");
  const [newModuleVariant, setNewModuleVariant] = useState("FY2-CE");
  const [newModuleSem, setNewModuleSem] = useState("Sem-1");
  const [moduleManageMsg, setModuleManageMsg] = useState("");
  const [staffAttendanceReport, setStaffAttendanceReport] = useState([]);
  const [staffResultReport, setStaffResultReport] = useState([]);
  const [attendanceReportFilter, setAttendanceReportFilter] = useState("all");
  const [resultReportFilter, setResultReportFilter] = useState("all");
  const [studentUploadFile, setStudentUploadFile] = useState(null);
  const [weeklyUploadFile, setWeeklyUploadFile] = useState(null);
  const [overallUploadFile, setOverallUploadFile] = useState(null);
  const [uploadRule, setUploadRule] = useState("both");
  const [studentUploadMsg, setStudentUploadMsg] = useState("");
  const [attendanceUploadMsg, setAttendanceUploadMsg] = useState("");
  const [studentFilter, setStudentFilter] = useState("");
  const [staffLoading, setStaffLoading] = useState(false);
  const [studentsPage, setStudentsPage] = useState(1);
  const [studentsHasMore, setStudentsHasMore] = useState(false);
  const [studentsTotal, setStudentsTotal] = useState(0);
  const [resultsPage, setResultsPage] = useState(1);
  const [resultsHasMore, setResultsHasMore] = useState(false);
  const [resultsTotal, setResultsTotal] = useState(0);
  const [studentsRefreshing, setStudentsRefreshing] = useState(false);
  const [studentsLoadingMore, setStudentsLoadingMore] = useState(false);
  const [studentsInitialLoading, setStudentsInitialLoading] = useState(false);
  const [resultsRefreshing, setResultsRefreshing] = useState(false);
  const [resultsLoadingMore, setResultsLoadingMore] = useState(false);
  const [resultsInitialLoading, setResultsInitialLoading] = useState(false);
  const [attendanceRefreshing, setAttendanceRefreshing] = useState(false);
  const [attendanceReportRefreshing, setAttendanceReportRefreshing] = useState(false);
  const [resultReportRefreshing, setResultReportRefreshing] = useState(false);
  const [attendanceVisible, setAttendanceVisible] = useState(PAGE_SIZE);
  const [attendanceReportVisible, setAttendanceReportVisible] = useState(PAGE_SIZE);
  const [resultReportVisible, setResultReportVisible] = useState(PAGE_SIZE);
  const [homeModulesVisible, setHomeModulesVisible] = useState(PAGE_SIZE);
  const [manageModulesVisible, setManageModulesVisible] = useState(PAGE_SIZE);
  const [toastMsg, setToastMsg] = useState("");
  const [toastVisible, setToastVisible] = useState(false);
  const [lastSync, setLastSync] = useState({
    home: null,
    modules: null,
    students: null,
    attendance: null,
    results: null,
    control: null,
  });

  useEffect(() => {
    (async () => {
      try {
        const saved = await AsyncStorage.getItem(MOBILE_THEME_KEY);
        if (saved === "light" || saved === "dark" || saved === "system") setThemeMode(saved);
      } catch (_) {}
    })();
  }, []);

  useEffect(() => {
    setCurrentUrl(apiBaseUrl);
  }, [apiBaseUrl]);

  const toggleTheme = async () => {
    const next = isDark ? "light" : "dark";
    setThemeMode(next);
    try {
      await AsyncStorage.setItem(MOBILE_THEME_KEY, next);
    } catch (_) {}
  };

  const roleLabel = useMemo(() => {
    if (role === "superadmin") return "SuperAdmin";
    if (role === "coordinator") return "Coordinator";
    return "Portal";
  }, [role]);
  const safeHost = useMemo(() => {
    try {
      const raw = String(currentUrl || "").trim();
      if (!raw) return "-";
      return raw.replace(/^https?:\/\//i, "").split("/")[0] || raw;
    } catch (_) {
      return String(currentUrl || "-");
    }
  }, [currentUrl]);

  const activeTabConfig = roleTabs.find((t) => t.key === activeTab) || roleTabs[0];
  const tabSubmenus = TAB_SUBMENUS[activeTab] || [{ key: "native", label: "Native" }];
  const activeSubmenuKey = submenuByTab[activeTab] || tabSubmenus[0].key;
  const activeSubmenu =
    tabSubmenus.find((s) => s.key === activeSubmenuKey) || tabSubmenus[0];
  const targetUrl = activeTabConfig.path
    ? `${currentUrl}${activeTabConfig.path}`
    : currentUrl;
  const submenuTargetUrl = activeSubmenu.path ? `${currentUrl}${activeSubmenu.path}` : "";
  const showSubmenuWebView = Boolean(activeSubmenu.path);
  const touchSync = (key) => {
    setLastSync((prev) => ({ ...prev, [key]: Date.now() }));
  };
  const formatSync = (value) => {
    if (!value) return "Not synced yet";
    const d = new Date(value);
    return `Last synced: ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  };
  const showToast = (msg) => {
    setToastMsg(msg || "Synced");
    setToastVisible(true);
    setTimeout(() => {
      setToastVisible(false);
    }, 1500);
  };
  const copyText = async (text, label = "Report") => {
    try {
      await Clipboard.setStringAsync(String(text || ""));
      showToast(`${label} copied`);
    } catch (_) {
      Alert.alert("Copy failed", "Could not copy report text.");
    }
  };

  const filteredAttendanceReportRows = useMemo(() => {
    if (attendanceReportFilter === "all") return staffAttendanceReport;
    if (attendanceReportFilter === "completed") {
      return staffAttendanceReport.filter((r) => Number(r.completion_percent) >= 100);
    }
    return staffAttendanceReport.filter((r) => Number(r.completion_percent) < 100);
  }, [staffAttendanceReport, attendanceReportFilter]);
  const pagedAttendanceReportRows = useMemo(
    () => filteredAttendanceReportRows.slice(0, attendanceReportVisible),
    [filteredAttendanceReportRows, attendanceReportVisible]
  );

  const filteredResultReportRows = useMemo(() => {
    if (resultReportFilter === "all") return staffResultReport;
    if (resultReportFilter === "completed") {
      return staffResultReport.filter((r) => Number(r.completion_percent) >= 100);
    }
    return staffResultReport.filter((r) => Number(r.completion_percent) < 100);
  }, [staffResultReport, resultReportFilter]);
  const pagedResultReportRows = useMemo(
    () => filteredResultReportRows.slice(0, resultReportVisible),
    [filteredResultReportRows, resultReportVisible]
  );

  const pagedAttendanceRows = useMemo(
    () => staffAttendanceRows.slice(0, attendanceVisible),
    [staffAttendanceRows, attendanceVisible]
  );
  const pagedHomeModules = useMemo(
    () => staffHomeModules.slice(0, homeModulesVisible),
    [staffHomeModules, homeModulesVisible]
  );
  const pagedManageModules = useMemo(
    () => staffManageModules.slice(0, manageModulesVisible),
    [staffManageModules, manageModulesVisible]
  );
  const attendanceReportStats = useMemo(() => {
    const rows = filteredAttendanceReportRows || [];
    const totalDefaulters = rows.reduce((a, r) => a + Number(r.need_call || 0), 0);
    const callsDone = rows.reduce((a, r) => a + Number(r.done || 0), 0);
    const notReceived = rows.reduce((a, r) => a + Number(r.not_received || 0), 0);
    const preInformed = rows.reduce((a, r) => a + Number(r.pre_informed || 0), 0);
    const avgDuration = (() => {
      const numer = rows.reduce((a, r) => a + Number(r.avg_duration || 0) * Number(r.done || 0), 0);
      const denom = Math.max(1, rows.reduce((a, r) => a + Number(r.done || 0), 0));
      return Math.round(numer / denom);
    })();
    return { totalDefaulters, callsDone, notReceived, preInformed, avgDuration };
  }, [filteredAttendanceReportRows]);
  const resultReportStatsNative = useMemo(() => {
    const rows = filteredResultReportRows || [];
    const totalDefaulters = rows.reduce((a, r) => a + Number(r.need_call || 0), 0);
    const callsDone = rows.reduce((a, r) => a + Number(r.done || 0), 0);
    const notReceived = rows.reduce((a, r) => a + Number(r.not_received || 0), 0);
    const preInformed = rows.reduce((a, r) => a + Number(r.pre_informed || 0), 0);
    const avgDuration = (() => {
      const numer = rows.reduce((a, r) => a + Number(r.avg_duration || 0) * Number(r.done || 0), 0);
      const denom = Math.max(1, rows.reduce((a, r) => a + Number(r.done || 0), 0));
      return Math.round(numer / denom);
    })();
    return { totalDefaulters, callsDone, notReceived, preInformed, avgDuration };
  }, [filteredResultReportRows]);
  const attendanceReportMessage = useMemo(
    () =>
      `Attendance WhatsApp Report\nTotal Defaulters: ${attendanceReportStats.totalDefaulters}\nCalls Done: ${attendanceReportStats.callsDone}\nNot Received: ${attendanceReportStats.notReceived}\nPre-informed: ${attendanceReportStats.preInformed}\nAvg Duration: ${attendanceReportStats.avgDuration} mins`,
    [attendanceReportStats]
  );
  const resultReportMessageNative = useMemo(
    () =>
      `Result WhatsApp Report\nTotal Defaulters: ${resultReportStatsNative.totalDefaulters}\nCalls Done: ${resultReportStatsNative.callsDone}\nNot Received: ${resultReportStatsNative.notReceived}\nPre-informed: ${resultReportStatsNative.preInformed}\nAvg Duration: ${resultReportStatsNative.avgDuration} mins`,
    [resultReportStatsNative]
  );

  const injectedCss = `
    (function() {
      try {
        var style = document.createElement('style');
        style.innerHTML = 'body{padding-bottom:8px !important;}';
        document.head.appendChild(style);
      } catch(e) {}
    })();
    true;
  `;

  useEffect(() => {
    (async () => {
      const saved = await AsyncStorage.getItem(STAFF_SESSION_KEY);
      if (!saved) return;
      try {
        const parsed = JSON.parse(saved);
        if (parsed.role === role && parsed.token) {
          setStaffToken(parsed.token);
          setStaffUser(parsed.username || "");
        }
      } catch (_) {}
    })();
  }, [role]);

  useEffect(() => {
    if (!staffToken) return;
    (async () => {
      try {
        const mod = await getStaffModules(staffToken, staffModuleId || "");
        setStaffModules(mod.modules || []);
        const selected = mod.selected_module_id || (mod.modules?.[0]?.module_id ?? null);
        setStaffModuleId(selected || null);
      } catch (_) {}
    })();
  }, [staffToken]);

  useEffect(() => {
    if (!staffToken || !staffModuleId) return;
    (async () => {
      try {
        const data = await getStaffSubjects(staffToken, staffModuleId);
        const list = data.subjects || [];
        setStaffSubjects(list);
        if (!resultUploadSubjectId && list.length) {
          setResultUploadSubjectId(String(list[0].id));
        }
      } catch (_) {
        setStaffSubjects([]);
      }
    })();
  }, [staffToken, staffModuleId]);

  useEffect(() => {
    if (!staffToken || !staffModuleId) return;
    (async () => {
      try {
        const data = await getStaffWeeks(staffToken, staffModuleId);
        const weeks = data.weeks || [];
        setStaffWeeks(weeks);
        setStaffWeek(data.latest_week || (weeks.length ? weeks[weeks.length - 1] : null));
      } catch (_) {
        setStaffWeeks([]);
        setStaffWeek(null);
      }
    })();
  }, [staffToken, staffModuleId]);

  useEffect(() => {
    if (!staffToken || !staffModuleId || !staffWeek) return;
    refreshAttendanceRows(false);
  }, [staffToken, staffModuleId, staffWeek]);

  useEffect(() => {
    if (!staffToken || !staffModuleId) return;
    (async () => {
      try {
        const data = await getStaffResultCycles(staffToken, staffModuleId);
        const cycles = data.cycles || [];
        setStaffResultCycles(cycles);
        setStaffResultUploadId(data.latest_upload_id || (cycles[0]?.upload_id ?? null));
      } catch (_) {
        setStaffResultCycles([]);
        setStaffResultUploadId(null);
      }
    })();
  }, [staffToken, staffModuleId]);

  useEffect(() => {
    if (!staffToken || !staffModuleId || !staffResultUploadId) return;
    fetchResultRowsPage(true);
  }, [staffToken, staffModuleId, staffResultUploadId, resultFilter]);

  useEffect(() => {
    if (!staffToken || !staffModuleId) return;
    const t = setTimeout(() => {
      fetchStudentsPage(true);
    }, 250);
    return () => clearTimeout(t);
  }, [staffToken, staffModuleId, studentFilter]);
  useEffect(() => {
    setAttendanceVisible(PAGE_SIZE);
  }, [staffAttendanceRows, staffWeek, staffModuleId]);
  useEffect(() => {
    setAttendanceReportVisible(PAGE_SIZE);
  }, [staffAttendanceReport, attendanceReportFilter, staffWeek, staffModuleId]);
  useEffect(() => {
    setResultReportVisible(PAGE_SIZE);
  }, [staffResultReport, resultReportFilter, staffResultUploadId, staffModuleId]);
  useEffect(() => {
    setHomeModulesVisible(PAGE_SIZE);
  }, [staffHomeModules]);
  useEffect(() => {
    setManageModulesVisible(PAGE_SIZE);
  }, [staffManageModules]);

  useEffect(() => {
    if (!staffToken || role !== "superadmin") return;
    refreshHomeSummary();
  }, [staffToken, role]);

  useEffect(() => {
    if (!staffToken || role !== "superadmin") return;
    refreshManageModules();
  }, [staffToken, role]);

  useEffect(() => {
    if (!staffToken || !staffModuleId) return;
    refreshControlSummary();
  }, [staffToken, staffModuleId, staffWeek, staffResultUploadId]);

  useEffect(() => {
    if (!staffToken || !staffModuleId) return;
    refreshAttendanceReport(false);
  }, [staffToken, staffModuleId, staffWeek]);

  useEffect(() => {
    if (!staffToken || !staffModuleId) return;
    refreshResultReport(false);
  }, [staffToken, staffModuleId, staffResultUploadId]);

  const fetchStudentsPage = async (reset = false) => {
    if (!staffToken || !staffModuleId) return;
    if (reset) {
      if (!staffStudents.length) setStudentsInitialLoading(true);
      setStudentsRefreshing(true);
    } else {
      if (studentsLoadingMore || !studentsHasMore) return;
      setStudentsLoadingMore(true);
    }
    const nextPage = reset ? 1 : studentsPage + 1;
    try {
      const data = await getStaffStudents(staffToken, staffModuleId, {
        page: nextPage,
        page_size: PAGE_SIZE,
        q: studentFilter || "",
      });
      const rows = data.students || [];
      setStaffStudents((prev) => (reset ? rows : [...prev, ...rows]));
      setStudentsPage(nextPage);
      setStudentsHasMore(Boolean(data.has_more));
      setStudentsTotal(Number(data.total || 0));
      touchSync("students");
    } catch (_) {
      if (reset) {
        setStaffStudents([]);
        setStudentsTotal(0);
      }
      setStudentsHasMore(false);
    } finally {
      if (reset) {
        setStudentsRefreshing(false);
        setStudentsInitialLoading(false);
      } else {
        setStudentsLoadingMore(false);
      }
    }
  };

  const fetchResultRowsPage = async (reset = false) => {
    if (!staffToken || !staffModuleId || !staffResultUploadId) return;
    if (reset) {
      if (!staffResultRows.length) setResultsInitialLoading(true);
      setResultsRefreshing(true);
    } else {
      if (resultsLoadingMore || !resultsHasMore) return;
      setResultsLoadingMore(true);
    }
    const nextPage = reset ? 1 : resultsPage + 1;
    const failFilter = resultFilter === "all" ? "all" : resultFilter;
    try {
      const data = await getStaffResultRows(staffToken, staffResultUploadId, staffModuleId, {
        page: nextPage,
        page_size: PAGE_SIZE,
        fail_filter: failFilter,
      });
      const rows = data.rows || [];
      setStaffResultRows((prev) => (reset ? rows : [...prev, ...rows]));
      setStaffResultMeta(data.upload || null);
      setResultsPage(nextPage);
      setResultsHasMore(Boolean(data.has_more));
      setResultsTotal(Number(data.total || 0));
      touchSync("results");
    } catch (_) {
      if (reset) {
        setStaffResultRows([]);
        setResultsTotal(0);
      }
      setResultsHasMore(false);
    } finally {
      if (reset) {
        setResultsRefreshing(false);
        setResultsInitialLoading(false);
      } else {
        setResultsLoadingMore(false);
      }
    }
  };

  const refreshAttendanceRows = async (showPull = false) => {
    if (!staffToken || !staffModuleId || !staffWeek) return;
    if (showPull) setAttendanceRefreshing(true);
    try {
      const data = await getStaffAttendance(staffToken, staffWeek, staffModuleId);
      setStaffAttendanceRows(data.rows || []);
      touchSync("attendance");
    } catch (_) {
      setStaffAttendanceRows([]);
    } finally {
      if (showPull) setAttendanceRefreshing(false);
    }
  };

  const refreshAttendanceReport = async (showPull = false) => {
    if (!staffToken || !staffModuleId) return;
    if (showPull) setAttendanceReportRefreshing(true);
    try {
      const data = await getStaffAttendanceReport(staffToken, staffModuleId, staffWeek || "");
      setStaffAttendanceReport(data.rows || []);
      touchSync("attendance");
    } catch (_) {
      setStaffAttendanceReport([]);
    } finally {
      if (showPull) setAttendanceReportRefreshing(false);
    }
  };

  const refreshResultReport = async (showPull = false) => {
    if (!staffToken || !staffModuleId) return;
    if (showPull) setResultReportRefreshing(true);
    try {
      const data = await getStaffResultReport(staffToken, staffModuleId, staffResultUploadId || "");
      setStaffResultReport(data.rows || []);
      touchSync("results");
    } catch (_) {
      setStaffResultReport([]);
    } finally {
      if (showPull) setResultReportRefreshing(false);
    }
  };

  const refreshHomeSummary = async () => {
    if (!staffToken || role !== "superadmin") return;
    try {
      const data = await getStaffHomeSummary(staffToken);
      setStaffHomeStats(data.stats || null);
      setStaffHomeModules(data.modules || []);
      touchSync("home");
    } catch (_) {
      setStaffHomeStats(null);
      setStaffHomeModules([]);
    }
  };

  const refreshManageModules = async () => {
    if (!staffToken || role !== "superadmin") return;
    try {
      const data = await getStaffModulesManage(staffToken);
      setStaffManageModules(data.modules || []);
      touchSync("modules");
    } catch (_) {
      setStaffManageModules([]);
    }
  };

  const refreshControlSummary = async () => {
    if (!staffToken || !staffModuleId) return;
    try {
      const data = await getStaffControlSummary(
        staffToken,
        staffModuleId,
        staffWeek || "",
        staffResultUploadId || ""
      );
      setStaffControl({
        week: data.week ?? null,
        attendance: data.attendance || [],
        result: data.result || [],
        result_upload: data.result_upload || null,
      });
      touchSync("control");
    } catch (_) {
      setStaffControl({ week: null, attendance: [], result: [], result_upload: null });
    }
  };

  const doStaffLogin = async () => {
    if (!staffUser.trim() || !staffPass.trim()) return;
    setStaffLoading(true);
    try {
      const data = await staffLogin(staffUser.trim(), staffPass);
      setStaffToken(data.token);
      await AsyncStorage.setItem(
        STAFF_SESSION_KEY,
        JSON.stringify({ role, username: staffUser.trim(), token: data.token })
      );
    } finally {
      setStaffLoading(false);
    }
  };

  const clearStaffSession = async () => {
    setStaffToken("");
    setStaffPass("");
    setStaffModules([]);
    setStaffStudents([]);
    setStaffWeeks([]);
    setStaffAttendanceRows([]);
    setStaffResultCycles([]);
    setStaffResultRows([]);
    setStaffResultUploadId(null);
    setStaffResultMeta(null);
    setStudentsPage(1);
    setStudentsHasMore(false);
    setStudentsTotal(0);
    setStudentsRefreshing(false);
    setStudentsLoadingMore(false);
    setStudentsInitialLoading(false);
    setResultsPage(1);
    setResultsHasMore(false);
    setResultsTotal(0);
    setResultsRefreshing(false);
    setResultsLoadingMore(false);
    setResultsInitialLoading(false);
    setAttendanceRefreshing(false);
    setAttendanceReportRefreshing(false);
    setResultReportRefreshing(false);
    setStaffSubjects([]);
    setResultUploadFile(null);
    setResultUploadMsg("");
    setStaffControl({ week: null, attendance: [], result: [], result_upload: null });
    setStaffAttendanceReport([]);
    setStaffResultReport([]);
    setStaffHomeStats(null);
    setStaffHomeModules([]);
    setStaffManageModules([]);
    setLastSync({
      home: null,
      modules: null,
      students: null,
      attendance: null,
      results: null,
      control: null,
    });
    setModuleManageMsg("");
    setStaffModuleId(null);
    setStaffWeek(null);
    await AsyncStorage.removeItem(STAFF_SESSION_KEY);
  };

  const doCreateModule = async () => {
    if (!newModuleName.trim() || !newModuleBatch.trim()) {
      Alert.alert("Required", "Module name and batch are required.");
      return;
    }
    setStaffLoading(true);
    try {
      const res = await createStaffModule(staffToken, {
        name: newModuleName.trim(),
        academic_batch: newModuleBatch.trim(),
        year_level: newModuleYear,
        variant: newModuleVariant,
        semester: newModuleSem,
      });
      setModuleManageMsg(res.msg || "Module created.");
      setNewModuleName("");
      const [mods, home] = await Promise.all([
        getStaffModulesManage(staffToken),
        getStaffHomeSummary(staffToken),
      ]);
      setStaffManageModules(mods.modules || []);
      setStaffHomeStats(home.stats || null);
      setStaffHomeModules(home.modules || []);
      touchSync("modules");
      touchSync("home");
    } catch (err) {
      Alert.alert("Create failed", String(err.message || err));
    } finally {
      setStaffLoading(false);
    }
  };

  const doToggleModule = async (moduleId, isActive) => {
    const action = isActive ? "archive" : "activate";
    setStaffLoading(true);
    try {
      const res = await toggleStaffModule(staffToken, moduleId, action);
      setModuleManageMsg(res.msg || "Updated.");
      const [mods, home] = await Promise.all([
        getStaffModulesManage(staffToken),
        getStaffHomeSummary(staffToken),
      ]);
      setStaffManageModules(mods.modules || []);
      setStaffHomeStats(home.stats || null);
      setStaffHomeModules(home.modules || []);
      touchSync("modules");
      touchSync("home");
    } catch (err) {
      Alert.alert("Update failed", String(err.message || err));
    } finally {
      setStaffLoading(false);
    }
  };

  const pickExcelFile = async (setter) => {
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: [
          "application/vnd.ms-excel",
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "application/octet-stream",
        ],
        copyToCacheDirectory: true,
      });
      if (res?.canceled) return;
      const file = res?.assets?.[0];
      if (file) setter(file);
    } catch (_) {}
  };

  const uploadMultipart = async (path, fields = {}, files = {}) => {
    if (!staffToken) throw new Error("Unauthorized");
    const form = new FormData();
    Object.entries(fields).forEach(([k, v]) => {
      if (v !== undefined && v !== null && String(v) !== "") {
        form.append(k, String(v));
      }
    });
    Object.entries(files).forEach(([k, f]) => {
      if (!f) return;
      form.append(k, {
        uri: f.uri,
        name: f.name || `${k}.xlsx`,
        type: f.mimeType || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
    });

    const response = await fetch(`${currentUrl}${path}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${staffToken}`,
        "X-Module-Id": String(staffModuleId || ""),
      },
      body: form,
    });
    const data = await response.json();
    if (!response.ok || data.ok === false) {
      throw new Error(data.msg || "Upload failed");
    }
    return data;
  };

  const doStudentUpload = async () => {
    if (!studentUploadFile) {
      Alert.alert("Select file", "Please select Student Master Excel first.");
      return;
    }
    setStaffLoading(true);
    try {
      const data = await uploadMultipart("/api/mobile/staff/upload-students/", {}, { file: studentUploadFile });
      setStudentUploadMsg(data.msg || "Upload done.");
      const sdata = await getStaffStudents(staffToken, staffModuleId);
      setStaffStudents(sdata.students || []);
    } catch (err) {
      Alert.alert("Upload failed", String(err.message || err));
    } finally {
      setStaffLoading(false);
    }
  };

  const doStudentClear = async () => {
    Alert.alert(
      "Confirm Delete",
      "Delete Student Master data for selected module?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            setStaffLoading(true);
            try {
              const response = await fetch(`${currentUrl}/api/mobile/staff/clear-students/`, {
                method: "POST",
                headers: {
                  Authorization: `Bearer ${staffToken}`,
                  "X-Module-Id": String(staffModuleId || ""),
                },
              });
              const data = await response.json();
              if (!response.ok || data.ok === false) throw new Error(data.msg || "Delete failed");
              setStudentUploadMsg(data.msg || "Deleted.");
              setStaffStudents([]);
            } catch (err) {
              Alert.alert("Delete failed", String(err.message || err));
            } finally {
              setStaffLoading(false);
            }
          },
        },
      ]
    );
  };

  const doAttendanceUpload = async () => {
    if (!staffWeek) {
      Alert.alert("Select week", "Please select week first.");
      return;
    }
    if (!weeklyUploadFile) {
      Alert.alert("Select file", "Please select weekly attendance file first.");
      return;
    }
    setStaffLoading(true);
    try {
      const files = {
        weekly_file: weeklyUploadFile,
        overall_file: staffWeek === 1 ? null : overallUploadFile,
      };
      const data = await uploadMultipart(
        "/api/mobile/staff/upload-attendance/",
        { week: staffWeek, rule: uploadRule },
        files
      );
      setAttendanceUploadMsg(data.msg || "Attendance uploaded.");
      const [attRows, rep] = await Promise.all([
        getStaffAttendance(staffToken, staffWeek, staffModuleId),
        getStaffAttendanceReport(staffToken, staffModuleId, staffWeek),
      ]);
      setStaffAttendanceRows(attRows.rows || []);
      setStaffAttendanceReport(rep.rows || []);
      touchSync("attendance");
    } catch (err) {
      Alert.alert("Upload failed", String(err.message || err));
    } finally {
      setStaffLoading(false);
    }
  };

  const doResultUpload = async () => {
    if (!resultUploadFile) {
      Alert.alert("Select file", "Please select result sheet first.");
      return;
    }
    const isAllExams = resultUploadTest === "ALL_EXAMS";
    if (!isAllExams && !resultUploadSubjectId) {
      Alert.alert("Select subject", "Please select subject.");
      return;
    }
    setStaffLoading(true);
    try {
      const data = await uploadMultipart(
        "/api/mobile/staff/upload-results/",
        {
          test_name: resultUploadTest,
          subject_id: isAllExams ? "ALL" : resultUploadSubjectId,
          upload_mode: isAllExams ? "compiled" : resultUploadMode,
          bulk_confirm: isAllExams ? "yes" : "",
        },
        { result_file: resultUploadFile }
      );
      setResultUploadMsg(data.msg || "Result upload completed.");
      const [cycles, rows, report] = await Promise.all([
        getStaffResultCycles(staffToken, staffModuleId),
        getStaffResultRows(staffToken, data.upload_id || "", staffModuleId, {
          page: 1,
          page_size: PAGE_SIZE,
          fail_filter: resultFilter,
        }),
        getStaffResultReport(staffToken, staffModuleId, data.upload_id || ""),
      ]);
      setStaffResultCycles(cycles.cycles || []);
      setStaffResultUploadId(data.upload_id || cycles.latest_upload_id || null);
      setStaffResultRows(rows.rows || []);
      setStaffResultMeta(rows.upload || null);
      setResultsPage(Number(rows.page || 1));
      setResultsHasMore(Boolean(rows.has_more));
      setResultsTotal(Number(rows.total || 0));
      setStaffResultReport(report.rows || []);
      touchSync("results");
    } catch (err) {
      Alert.alert("Upload failed", String(err.message || err));
    } finally {
      setStaffLoading(false);
    }
  };

  return (
    <SafeAreaView style={[styles.portalPage, { backgroundColor: palette.pageBg }]}>
      <StatusBar barStyle="light-content" backgroundColor={APP_COLORS.primary} />

      <View style={[styles.portalHeader, { backgroundColor: palette.headerBg }]}>
        <View>
          <Text style={[styles.portalTitle, { color: palette.headerText }]}>{roleLabel} Mobile</Text>
          <Text style={[styles.portalSub, { color: palette.headerSub }]}>
            {`Login with your existing ${roleLabel} account • ${safeHost}`}
          </Text>
        </View>
        <TouchableOpacity style={styles.overflowButton} onPress={() => setHeaderMenuOpen(true)}>
          <Text style={styles.overflowButtonText}>⋮</Text>
        </TouchableOpacity>
      </View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        style={[styles.submenuBar, { backgroundColor: palette.submenuBg, borderBottomColor: palette.submenuBorder }]}
        contentContainerStyle={styles.submenuContent}
      >
        {tabSubmenus.map((s) => (
          <TouchableOpacity
            key={`${activeTab}-${s.key}`}
            style={[
              styles.submenuChip,
              { backgroundColor: palette.chipBg, borderColor: palette.chipBorder },
              activeSubmenu.key === s.key && styles.submenuChipActive,
              activeSubmenu.key === s.key && { backgroundColor: palette.chipActiveBg, borderColor: palette.chipActiveBg },
            ]}
            onPress={() =>
              setSubmenuByTab((prev) => ({
                ...prev,
                [activeTab]: s.key,
              }))
            }
          >
            <Text
              style={[
                styles.submenuChipText,
                { color: palette.chipText },
                activeSubmenu.key === s.key && styles.submenuChipTextActive,
                activeSubmenu.key === s.key && { color: palette.chipActiveText },
              ]}
            >
              {s.label}
            </Text>
          </TouchableOpacity>
        ))}
      </ScrollView>

      <View style={styles.portalBody}>
        {showSubmenuWebView ? (
          <WebView
            key={`submenu-${activeTab}-${activeSubmenu.key}-${reloadKey}`}
            source={{ uri: submenuTargetUrl }}
            style={styles.webview}
            sharedCookiesEnabled
            javaScriptEnabled
            domStorageEnabled
            startInLoadingState
            injectedJavaScript={injectedCss}
          />
        ) : activeTab === "home" ? (
          !staffToken ? (
            <View style={styles.infoPanel}>
              <Text style={styles.infoTitle}>SuperAdmin Login</Text>
              <TextInput
                value={staffUser}
                onChangeText={setStaffUser}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Username"
                style={styles.serverInput}
              />
              <TextInput
                value={staffPass}
                onChangeText={setStaffPass}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Password"
                secureTextEntry
                style={[styles.serverInput, { marginTop: 8 }]}
              />
              <TouchableOpacity style={styles.applyBtn} onPress={doStaffLogin} disabled={staffLoading}>
                <Text style={styles.applyBtnText}>{staffLoading ? "Please wait..." : "Login"}</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View style={styles.studentsWrap}>
              <Text style={styles.infoTitle}>SuperAdmin Home</Text>
              <View style={styles.syncRow}>
                <Text style={styles.syncText}>{formatSync(lastSync.home)}</Text>
                <TouchableOpacity
                  style={styles.syncBtn}
                  onPress={async () => {
                    await refreshHomeSummary();
                    showToast("Synced");
                  }}
                  disabled={staffLoading}
                >
                  <Text style={styles.syncBtnText}>Sync now</Text>
                </TouchableOpacity>
              </View>
              {staffHomeStats ? (
                <View style={styles.statsGrid}>
                  <View style={styles.statCard}>
                    <Text style={styles.statLabel}>Coordinators</Text>
                    <Text style={styles.statValue}>{staffHomeStats.total_coordinators}</Text>
                  </View>
                  <View style={styles.statCard}>
                    <Text style={styles.statLabel}>Modules</Text>
                    <Text style={styles.statValue}>{staffHomeStats.total_modules}</Text>
                  </View>
                  <View style={styles.statCard}>
                    <Text style={styles.statLabel}>Mentors</Text>
                    <Text style={styles.statValue}>{staffHomeStats.total_mentors}</Text>
                  </View>
                  <View style={styles.statCard}>
                    <Text style={styles.statLabel}>Students</Text>
                    <Text style={styles.statValue}>{staffHomeStats.total_students}</Text>
                  </View>
                </View>
              ) : null}
              <Text style={[styles.infoTitle, { fontSize: 15, marginTop: 8 }]}>Module Snapshot</Text>
              <FlatList
                data={pagedHomeModules}
                keyExtractor={(m) => String(m.id)}
                initialNumToRender={12}
                windowSize={8}
                renderItem={({ item }) => (
                  <View style={styles.studentCard}>
                    <Text style={styles.studentName}>{item.name}</Text>
                    <Text style={styles.studentMeta}>
                      {item.variant} | {item.semester} | Batch {item.batch}
                    </Text>
                    <Text style={styles.studentMeta}>
                      Students: {item.students} | Mentors: {item.mentors} | Coordinators: {item.coordinators}
                    </Text>
                  </View>
                )}
              />
              {pagedHomeModules.length < staffHomeModules.length ? (
                <TouchableOpacity style={styles.loadMoreBtn} onPress={() => setHomeModulesVisible((n) => n + PAGE_SIZE)}>
                  <Text style={styles.loadMoreText}>Load More</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          )
        ) : activeTab === "modules" ? (
          !staffToken ? (
            <View style={styles.infoPanel}>
              <Text style={styles.infoTitle}>SuperAdmin Login</Text>
              <TextInput
                value={staffUser}
                onChangeText={setStaffUser}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Username"
                style={styles.serverInput}
              />
              <TextInput
                value={staffPass}
                onChangeText={setStaffPass}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Password"
                secureTextEntry
                style={[styles.serverInput, { marginTop: 8 }]}
              />
              <TouchableOpacity style={styles.applyBtn} onPress={doStaffLogin} disabled={staffLoading}>
                <Text style={styles.applyBtnText}>{staffLoading ? "Please wait..." : "Login"}</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View style={styles.studentsWrap}>
              <Text style={styles.infoTitle}>Manage Modules</Text>
              <View style={styles.syncRow}>
                <Text style={styles.syncText}>{formatSync(lastSync.modules)}</Text>
                <TouchableOpacity
                  style={styles.syncBtn}
                  onPress={async () => {
                    await refreshManageModules();
                    showToast("Synced");
                  }}
                  disabled={staffLoading}
                >
                  <Text style={styles.syncBtnText}>Sync now</Text>
                </TouchableOpacity>
              </View>
              <TextInput
                value={newModuleName}
                onChangeText={setNewModuleName}
                placeholder="Module name"
                style={[styles.serverInput, { marginBottom: 8 }]}
              />
              <TextInput
                value={newModuleBatch}
                onChangeText={setNewModuleBatch}
                placeholder="Academic batch (e.g. 2026-29)"
                style={[styles.serverInput, { marginBottom: 8 }]}
              />
              <View style={styles.filterRow}>
                {["FY", "SY", "TY", "LY"].map((yy) => (
                  <TouchableOpacity key={yy} style={[styles.filterBtn, newModuleYear === yy && styles.filterBtnActive]} onPress={() => setNewModuleYear(yy)}>
                    <Text style={[styles.filterBtnText, newModuleYear === yy && styles.filterBtnTextActive]}>{yy}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <View style={styles.filterRow}>
                {["FY1", "FY2-CE", "FY2-Non CE", "FY3", "FY4", "FY5"].map((vv) => (
                  <TouchableOpacity key={vv} style={[styles.filterBtn, newModuleVariant === vv && styles.filterBtnActive]} onPress={() => setNewModuleVariant(vv)}>
                    <Text style={[styles.filterBtnText, newModuleVariant === vv && styles.filterBtnTextActive]}>{vv}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <View style={styles.filterRow}>
                {["Sem-1", "Sem-2"].map((ss) => (
                  <TouchableOpacity key={ss} style={[styles.filterBtn, newModuleSem === ss && styles.filterBtnActive]} onPress={() => setNewModuleSem(ss)}>
                    <Text style={[styles.filterBtnText, newModuleSem === ss && styles.filterBtnTextActive]}>{ss}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <TouchableOpacity style={styles.applyBtn} onPress={doCreateModule} disabled={staffLoading}>
                <Text style={styles.applyBtnText}>{staffLoading ? "Please wait..." : "Create Module"}</Text>
              </TouchableOpacity>
              {moduleManageMsg ? <Text style={styles.uploadMsg}>{moduleManageMsg}</Text> : null}
              <FlatList
                data={pagedManageModules}
                keyExtractor={(m) => String(m.id)}
                initialNumToRender={12}
                windowSize={8}
                renderItem={({ item }) => (
                  <View style={styles.studentCard}>
                    <Text style={styles.studentName}>{item.name}</Text>
                    <Text style={styles.studentMeta}>
                      {item.variant} | {item.semester} | Batch {item.batch}
                    </Text>
                    <View style={styles.actionRow}>
                      <TouchableOpacity
                        style={item.is_active ? styles.smallDanger : styles.smallBtnPrimary}
                        onPress={() => doToggleModule(item.id, item.is_active)}
                      >
                        <Text style={item.is_active ? styles.smallDangerText : styles.smallBtnPrimaryText}>
                          {item.is_active ? "Archive" : "Activate"}
                        </Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                )}
              />
              {pagedManageModules.length < staffManageModules.length ? (
                <TouchableOpacity style={styles.loadMoreBtn} onPress={() => setManageModulesVisible((n) => n + PAGE_SIZE)}>
                  <Text style={styles.loadMoreText}>Load More</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          )
        ) : activeTab === "students" ? (
          !staffToken ? (
            <View style={styles.infoPanel}>
              <Text style={styles.infoTitle}>Native Students Login</Text>
              <TextInput
                value={staffUser}
                onChangeText={setStaffUser}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Username"
                style={styles.serverInput}
              />
              <TextInput
                value={staffPass}
                onChangeText={setStaffPass}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Password"
                secureTextEntry
                style={[styles.serverInput, { marginTop: 8 }]}
              />
              <TouchableOpacity style={styles.applyBtn} onPress={doStaffLogin} disabled={staffLoading}>
                <Text style={styles.applyBtnText}>{staffLoading ? "Please wait..." : "Login"}</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View style={styles.studentsWrap}>
              <View style={styles.studentsTopRow}>
                <Text style={styles.infoTitle}>Students ({studentsTotal})</Text>
                <TouchableOpacity style={styles.smallDanger} onPress={clearStaffSession}>
                  <Text style={styles.smallDangerText}>Logout</Text>
                </TouchableOpacity>
              </View>
              <View style={styles.syncRow}>
                <Text style={styles.syncText}>{formatSync(lastSync.students)}</Text>
                <TouchableOpacity
                  style={styles.syncBtn}
                  onPress={async () => {
                    await fetchStudentsPage(true);
                    showToast("Synced");
                  }}
                  disabled={staffLoading}
                >
                  <Text style={styles.syncBtnText}>Sync now</Text>
                </TouchableOpacity>
              </View>
              <FlatList
                horizontal
                showsHorizontalScrollIndicator={false}
                data={staffModules}
                keyExtractor={(m) => String(m.module_id)}
                style={{ maxHeight: 44, marginBottom: 8 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[
                      styles.moduleChip,
                      staffModuleId === item.module_id && styles.moduleChipActive,
                    ]}
                    onPress={() => setStaffModuleId(item.module_id)}
                  >
                    <Text
                      style={[
                        styles.moduleChipText,
                        staffModuleId === item.module_id && styles.moduleChipTextActive,
                      ]}
                    >
                      {item.name}
                    </Text>
                  </TouchableOpacity>
                )}
              />
              <View style={styles.actionRow}>
                <TouchableOpacity style={styles.smallBtn} onPress={() => pickExcelFile(setStudentUploadFile)}>
                  <Text style={styles.smallBtnText}>
                    {studentUploadFile ? `File: ${studentUploadFile.name}` : "Choose File"}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.smallBtnPrimary} onPress={doStudentUpload} disabled={staffLoading}>
                  <Text style={styles.smallBtnPrimaryText}>Upload</Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.smallDanger} onPress={doStudentClear} disabled={staffLoading}>
                  <Text style={styles.smallDangerText}>Delete Data</Text>
                </TouchableOpacity>
              </View>
              {studentUploadMsg ? <Text style={styles.uploadMsg}>{studentUploadMsg}</Text> : null}
              <TextInput
                value={studentFilter}
                onChangeText={setStudentFilter}
                placeholder="Filter students..."
                style={[styles.serverInput, { marginBottom: 8 }]}
              />
              {studentsInitialLoading && !staffStudents.length ? (
                <View>
                  {[0, 1, 2].map((n) => (
                    <View style={styles.skeletonCard} key={`student-skeleton-${n}`}>
                      <View style={[styles.skeletonLine, { width: "65%" }]} />
                      <View style={[styles.skeletonLine, { width: "50%" }]} />
                      <View style={[styles.skeletonLine, { width: "45%" }]} />
                    </View>
                  ))}
                </View>
              ) : (
                <FlatList
                  data={staffStudents}
                  keyExtractor={(s, idx) => `${s.enrollment || "x"}-${idx}`}
                  initialNumToRender={16}
                  windowSize={9}
                  refreshing={studentsRefreshing}
                  onRefresh={() => fetchStudentsPage(true)}
                  onEndReachedThreshold={0.4}
                  onEndReached={() => fetchStudentsPage(false)}
                  ListFooterComponent={
                    studentsLoadingMore ? (
                      <View style={styles.listFooter}>
                        <ActivityIndicator color={APP_COLORS.accent} size="small" />
                      </View>
                    ) : !studentsHasMore && staffStudents.length ? (
                      <Text style={styles.listEndText}>No more records</Text>
                    ) : null
                  }
                  renderItem={({ item }) => (
                    <View style={styles.studentCard}>
                      <Text style={styles.studentName}>
                        {item.roll_no || "-"} | {item.name}
                      </Text>
                      <Text style={styles.studentMeta}>{item.enrollment} | {item.branch || "-"}</Text>
                      <Text style={styles.studentMeta}>Mentor: {item.mentor || "-"}</Text>
                      <Text style={styles.studentMeta}>Student: {item.student_mobile || "-"}</Text>
                      <Text style={styles.studentMeta}>Father: {item.father_mobile || "-"}</Text>
                    </View>
                  )}
                />
              )}
            </View>
          )
        ) : activeTab === "attendance" ? (
          !staffToken ? (
            <View style={styles.infoPanel}>
              <Text style={styles.infoTitle}>Native Attendance Login</Text>
              <TextInput
                value={staffUser}
                onChangeText={setStaffUser}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Username"
                style={styles.serverInput}
              />
              <TextInput
                value={staffPass}
                onChangeText={setStaffPass}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Password"
                secureTextEntry
                style={[styles.serverInput, { marginTop: 8 }]}
              />
              <TouchableOpacity style={styles.applyBtn} onPress={doStaffLogin} disabled={staffLoading}>
                <Text style={styles.applyBtnText}>{staffLoading ? "Please wait..." : "Login"}</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View style={styles.studentsWrap}>
              <View style={styles.studentsTopRow}>
                <Text style={styles.infoTitle}>Attendance (Week {staffWeek || "-"})</Text>
              </View>
              <View style={styles.syncRow}>
                <Text style={styles.syncText}>{formatSync(lastSync.attendance)}</Text>
                <TouchableOpacity
                  style={styles.syncBtn}
                  onPress={async () => {
                    await Promise.all([refreshAttendanceRows(true), refreshAttendanceReport(true)]);
                    showToast("Synced");
                  }}
                  disabled={staffLoading}
                >
                  <Text style={styles.syncBtnText}>Sync now</Text>
                </TouchableOpacity>
              </View>
              <FlatList
                horizontal
                showsHorizontalScrollIndicator={false}
                data={staffModules}
                keyExtractor={(m) => String(m.module_id)}
                style={{ maxHeight: 44, marginBottom: 8 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[
                      styles.moduleChip,
                      staffModuleId === item.module_id && styles.moduleChipActive,
                    ]}
                    onPress={() => setStaffModuleId(item.module_id)}
                  >
                    <Text
                      style={[
                        styles.moduleChipText,
                        staffModuleId === item.module_id && styles.moduleChipTextActive,
                      ]}
                    >
                      {item.name}
                    </Text>
                  </TouchableOpacity>
                )}
              />
              <FlatList
                horizontal
                showsHorizontalScrollIndicator={false}
                data={staffWeeks}
                keyExtractor={(w, idx) => `${w}-${idx}`}
                style={{ maxHeight: 44, marginBottom: 8 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[styles.moduleChip, staffWeek === item && styles.moduleChipActive]}
                    onPress={() => setStaffWeek(item)}
                  >
                    <Text style={[styles.moduleChipText, staffWeek === item && styles.moduleChipTextActive]}>
                      Week {item}
                    </Text>
                  </TouchableOpacity>
                )}
              />
              <View style={styles.filterRow}>
                <TouchableOpacity style={[styles.filterBtn, uploadRule === "both" && styles.filterBtnActive]} onPress={() => setUploadRule("both")}>
                  <Text style={[styles.filterBtnText, uploadRule === "both" && styles.filterBtnTextActive]}>Both &lt;80</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, uploadRule === "week" && styles.filterBtnActive]} onPress={() => setUploadRule("week")}>
                  <Text style={[styles.filterBtnText, uploadRule === "week" && styles.filterBtnTextActive]}>Week &lt;80</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, uploadRule === "overall" && styles.filterBtnActive]} onPress={() => setUploadRule("overall")}>
                  <Text style={[styles.filterBtnText, uploadRule === "overall" && styles.filterBtnTextActive]}>Overall &lt;80</Text>
                </TouchableOpacity>
              </View>
              <View style={styles.actionRow}>
                <TouchableOpacity style={styles.smallBtn} onPress={() => pickExcelFile(setWeeklyUploadFile)}>
                  <Text style={styles.smallBtnText}>
                    {weeklyUploadFile ? `Weekly: ${weeklyUploadFile.name}` : "Weekly File"}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.smallBtn} onPress={() => pickExcelFile(setOverallUploadFile)}>
                  <Text style={styles.smallBtnText}>
                    {overallUploadFile ? `Overall: ${overallUploadFile.name}` : "Overall File"}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.smallBtnPrimary} onPress={doAttendanceUpload} disabled={staffLoading}>
                  <Text style={styles.smallBtnPrimaryText}>Upload</Text>
                </TouchableOpacity>
              </View>
              {attendanceUploadMsg ? <Text style={styles.uploadMsg}>{attendanceUploadMsg}</Text> : null}
              <FlatList
                data={pagedAttendanceRows}
                keyExtractor={(r, idx) => `${r.enrollment || "x"}-${idx}`}
                initialNumToRender={16}
                windowSize={9}
                refreshing={attendanceRefreshing}
                onRefresh={() => refreshAttendanceRows(true)}
                renderItem={({ item }) => {
                  const wk = Number(item.week_percentage);
                  const ov = Number(item.overall_percentage);
                  const wkLow = !Number.isNaN(wk) && wk < 80;
                  const ovLow = !Number.isNaN(ov) && ov < 80;
                  return (
                    <View style={styles.studentCard}>
                      <Text style={styles.studentName}>
                        {item.roll_no || "-"} | {item.name}
                      </Text>
                      <Text style={styles.studentMeta}>{item.enrollment} | Mentor: {item.mentor || "-"}</Text>
                      <Text style={[styles.studentMeta, wkLow && styles.lowText]}>
                        Week %: {item.week_percentage ?? "-"}
                      </Text>
                      <Text style={[styles.studentMeta, ovLow && styles.lowText]}>
                        Overall %: {item.overall_percentage ?? "-"}
                      </Text>
                      <Text style={styles.studentMeta}>
                        Call required: {item.call_required ? "Yes" : "No"} | Status: {item.call_status || "Pending"}
                      </Text>
                    </View>
                  );
                }}
              />
              {pagedAttendanceRows.length < staffAttendanceRows.length ? (
                <TouchableOpacity style={styles.loadMoreBtn} onPress={() => setAttendanceVisible((n) => n + PAGE_SIZE)}>
                  <Text style={styles.loadMoreText}>Load More</Text>
                </TouchableOpacity>
              ) : null}
              <Text style={[styles.infoTitle, { fontSize: 15, marginTop: 8 }]}>Attendance Report (Mentor-wise)</Text>
              <View style={styles.reportStatsGrid}>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Total Defaulters</Text>
                  <Text style={styles.reportStatValue}>{attendanceReportStats.totalDefaulters}</Text>
                </View>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Calls Done</Text>
                  <Text style={styles.reportStatValue}>{attendanceReportStats.callsDone}</Text>
                </View>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Not Received</Text>
                  <Text style={styles.reportStatValue}>{attendanceReportStats.notReceived}</Text>
                </View>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Pre-informed</Text>
                  <Text style={styles.reportStatValue}>{attendanceReportStats.preInformed}</Text>
                </View>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Avg Duration</Text>
                  <Text style={styles.reportStatValue}>{attendanceReportStats.avgDuration}m</Text>
                </View>
              </View>
              <TouchableOpacity style={styles.applyBtn} onPress={() => copyText(attendanceReportMessage, "Attendance report")}>
                <Text style={styles.applyBtnText}>Copy WhatsApp Report</Text>
              </TouchableOpacity>
              <View style={styles.reportPreviewBox}>
                <Text style={styles.reportPreviewText}>{attendanceReportMessage}</Text>
              </View>
              <View style={styles.filterRow}>
                <TouchableOpacity style={[styles.filterBtn, attendanceReportFilter === "all" && styles.filterBtnActive]} onPress={() => setAttendanceReportFilter("all")}>
                  <Text style={[styles.filterBtnText, attendanceReportFilter === "all" && styles.filterBtnTextActive]}>All</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, attendanceReportFilter === "completed" && styles.filterBtnActive]} onPress={() => setAttendanceReportFilter("completed")}>
                  <Text style={[styles.filterBtnText, attendanceReportFilter === "completed" && styles.filterBtnTextActive]}>Completed</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, attendanceReportFilter === "pending" && styles.filterBtnActive]} onPress={() => setAttendanceReportFilter("pending")}>
                  <Text style={[styles.filterBtnText, attendanceReportFilter === "pending" && styles.filterBtnTextActive]}>Pending</Text>
                </TouchableOpacity>
              </View>
              <FlatList
                data={pagedAttendanceReportRows}
                keyExtractor={(r, idx) => `${r.mentor}-${idx}`}
                initialNumToRender={12}
                windowSize={8}
                refreshing={attendanceReportRefreshing}
                onRefresh={() => refreshAttendanceReport(true)}
                renderItem={({ item }) => (
                  <View style={styles.studentCard}>
                    <Text style={styles.studentName}>{item.mentor}</Text>
                    <Text style={styles.studentMeta}>
                      Students: {item.students} | Need: {item.need_call} | Done: {item.done}
                    </Text>
                    <Text style={styles.studentMeta}>
                      Received: {item.received} | Not Received: {item.not_received} | Msg: {item.msg_sent}
                    </Text>
                    <Text style={[styles.studentMeta, Number(item.completion_percent) < 100 && styles.lowText]}>
                      Completion: {item.completion_percent}%
                    </Text>
                  </View>
                )}
              />
              {pagedAttendanceReportRows.length < filteredAttendanceReportRows.length ? (
                <TouchableOpacity style={styles.loadMoreBtn} onPress={() => setAttendanceReportVisible((n) => n + PAGE_SIZE)}>
                  <Text style={styles.loadMoreText}>Load More</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          )
        ) : activeTab === "results" ? (
          !staffToken ? (
            <View style={styles.infoPanel}>
              <Text style={styles.infoTitle}>Native Results Login</Text>
              <TextInput
                value={staffUser}
                onChangeText={setStaffUser}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Username"
                style={styles.serverInput}
              />
              <TextInput
                value={staffPass}
                onChangeText={setStaffPass}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Password"
                secureTextEntry
                style={[styles.serverInput, { marginTop: 8 }]}
              />
              <TouchableOpacity style={styles.applyBtn} onPress={doStaffLogin} disabled={staffLoading}>
                <Text style={styles.applyBtnText}>{staffLoading ? "Please wait..." : "Login"}</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View style={styles.studentsWrap}>
              <View style={styles.studentsTopRow}>
                <Text style={styles.infoTitle}>
                  Results ({resultsTotal})
                </Text>
              </View>
              <View style={styles.syncRow}>
                <Text style={styles.syncText}>{formatSync(lastSync.results)}</Text>
                <TouchableOpacity
                  style={styles.syncBtn}
                  onPress={async () => {
                    await Promise.all([fetchResultRowsPage(true), refreshResultReport(true)]);
                    showToast("Synced");
                  }}
                  disabled={staffLoading}
                >
                  <Text style={styles.syncBtnText}>Sync now</Text>
                </TouchableOpacity>
              </View>
              <FlatList
                horizontal
                showsHorizontalScrollIndicator={false}
                data={staffModules}
                keyExtractor={(m) => String(m.module_id)}
                style={{ maxHeight: 44, marginBottom: 8 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[
                      styles.moduleChip,
                      staffModuleId === item.module_id && styles.moduleChipActive,
                    ]}
                    onPress={() => setStaffModuleId(item.module_id)}
                  >
                    <Text
                      style={[
                        styles.moduleChipText,
                        staffModuleId === item.module_id && styles.moduleChipTextActive,
                      ]}
                    >
                      {item.name}
                    </Text>
                  </TouchableOpacity>
                )}
              />
              <FlatList
                horizontal
                showsHorizontalScrollIndicator={false}
                data={["T1", "T2", "T3", "T4", "REMEDIAL", "ALL_EXAMS"]}
                keyExtractor={(t) => t}
                style={{ maxHeight: 44, marginBottom: 8 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[styles.moduleChip, resultUploadTest === item && styles.moduleChipActive]}
                    onPress={() => setResultUploadTest(item)}
                  >
                    <Text style={[styles.moduleChipText, resultUploadTest === item && styles.moduleChipTextActive]}>
                      {item}
                    </Text>
                  </TouchableOpacity>
                )}
              />
              {resultUploadTest !== "ALL_EXAMS" ? (
                <FlatList
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  data={staffSubjects}
                  keyExtractor={(s) => String(s.id)}
                  style={{ maxHeight: 44, marginBottom: 8 }}
                  renderItem={({ item }) => (
                    <TouchableOpacity
                      style={[styles.moduleChip, String(resultUploadSubjectId) === String(item.id) && styles.moduleChipActive]}
                      onPress={() => setResultUploadSubjectId(String(item.id))}
                    >
                      <Text style={[styles.moduleChipText, String(resultUploadSubjectId) === String(item.id) && styles.moduleChipTextActive]}>
                        {item.short_name || item.name}
                      </Text>
                    </TouchableOpacity>
                  )}
                />
              ) : null}
              <View style={styles.filterRow}>
                <TouchableOpacity style={[styles.filterBtn, resultUploadMode === "subject" && styles.filterBtnActive]} onPress={() => setResultUploadMode("subject")}>
                  <Text style={[styles.filterBtnText, resultUploadMode === "subject" && styles.filterBtnTextActive]}>Subject Sheet</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, resultUploadMode === "compiled" && styles.filterBtnActive]} onPress={() => setResultUploadMode("compiled")}>
                  <Text style={[styles.filterBtnText, resultUploadMode === "compiled" && styles.filterBtnTextActive]}>Compiled Sheet</Text>
                </TouchableOpacity>
              </View>
              <View style={styles.actionRow}>
                <TouchableOpacity style={styles.smallBtn} onPress={() => pickExcelFile(setResultUploadFile)}>
                  <Text style={styles.smallBtnText}>
                    {resultUploadFile ? `File: ${resultUploadFile.name}` : "Choose Result File"}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity style={styles.smallBtnPrimary} onPress={doResultUpload} disabled={staffLoading}>
                  <Text style={styles.smallBtnPrimaryText}>Upload Result</Text>
                </TouchableOpacity>
              </View>
              {resultUploadMsg ? <Text style={styles.uploadMsg}>{resultUploadMsg}</Text> : null}
              <FlatList
                horizontal
                showsHorizontalScrollIndicator={false}
                data={staffResultCycles}
                keyExtractor={(c) => String(c.upload_id)}
                style={{ maxHeight: 44, marginBottom: 8 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[
                      styles.moduleChip,
                      staffResultUploadId === item.upload_id && styles.moduleChipActive,
                    ]}
                    onPress={() => setStaffResultUploadId(item.upload_id)}
                  >
                    <Text
                      style={[
                        styles.moduleChipText,
                        staffResultUploadId === item.upload_id && styles.moduleChipTextActive,
                      ]}
                    >
                      {item.test_name}-{item.subject_name}
                    </Text>
                  </TouchableOpacity>
                )}
              />
              <View style={styles.filterRow}>
                <TouchableOpacity style={[styles.filterBtn, resultFilter === "all" && styles.filterBtnActive]} onPress={() => setResultFilter("all")}>
                  <Text style={[styles.filterBtnText, resultFilter === "all" && styles.filterBtnTextActive]}>All</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, resultFilter === "current" && styles.filterBtnActive]} onPress={() => setResultFilter("current")}>
                  <Text style={[styles.filterBtnText, resultFilter === "current" && styles.filterBtnTextActive]}>Current Fail</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, resultFilter === "total" && styles.filterBtnActive]} onPress={() => setResultFilter("total")}>
                  <Text style={[styles.filterBtnText, resultFilter === "total" && styles.filterBtnTextActive]}>Cumulative Fail</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, resultFilter === "either" && styles.filterBtnActive]} onPress={() => setResultFilter("either")}>
                  <Text style={[styles.filterBtnText, resultFilter === "either" && styles.filterBtnTextActive]}>Either OR</Text>
                </TouchableOpacity>
              </View>
              {staffResultMeta ? (
                <Text style={styles.studentMeta}>
                  {staffResultMeta.test_name} - {staffResultMeta.subject_name} | Matched: {staffResultMeta.rows_matched} | Failed: {staffResultMeta.rows_failed}
                </Text>
              ) : null}
              {resultsInitialLoading && !staffResultRows.length ? (
                <View>
                  {[0, 1, 2].map((n) => (
                    <View style={styles.skeletonCard} key={`result-skeleton-${n}`}>
                      <View style={[styles.skeletonLine, { width: "62%" }]} />
                      <View style={[styles.skeletonLine, { width: "48%" }]} />
                      <View style={[styles.skeletonLine, { width: "70%" }]} />
                    </View>
                  ))}
                </View>
              ) : (
                <FlatList
                  data={staffResultRows}
                  keyExtractor={(r, idx) => `${r.enrollment || "x"}-${idx}`}
                  initialNumToRender={16}
                  windowSize={9}
                  refreshing={resultsRefreshing}
                  onRefresh={() => fetchResultRowsPage(true)}
                  onEndReachedThreshold={0.4}
                  onEndReached={() => fetchResultRowsPage(false)}
                  ListFooterComponent={
                    resultsLoadingMore ? (
                      <View style={styles.listFooter}>
                        <ActivityIndicator color={APP_COLORS.accent} size="small" />
                      </View>
                    ) : !resultsHasMore && staffResultRows.length ? (
                      <Text style={styles.listEndText}>No more records</Text>
                    ) : null
                  }
                  renderItem={({ item }) => (
                    <View style={styles.studentCard}>
                      <Text style={styles.studentName}>
                        {item.roll_no || "-"} | {item.name}
                      </Text>
                      <Text style={styles.studentMeta}>{item.enrollment} | Mentor: {item.mentor || "-"}</Text>
                      <Text style={[styles.studentMeta, item.current_fail && styles.lowText]}>
                        Current: {item.marks_current ?? "-"}
                      </Text>
                      <Text style={[styles.studentMeta, item.total_fail && styles.lowText]}>
                        Total: {item.marks_total ?? "-"}
                      </Text>
                      <Text style={styles.studentMeta}>
                        T1: {item.marks_t1 ?? "-"} | T2: {item.marks_t2 ?? "-"} | T3: {item.marks_t3 ?? "-"} | T4: {item.marks_t4 ?? "-"}
                      </Text>
                      <Text style={[styles.studentMeta, item.either_fail && styles.lowText]}>
                        {item.fail_reason || (item.either_fail ? "Fail as per rule" : "Pass")}
                      </Text>
                    </View>
                  )}
                />
              )}
              <Text style={[styles.infoTitle, { fontSize: 15, marginTop: 8 }]}>Result Report (Mentor-wise)</Text>
              <View style={styles.reportStatsGrid}>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Total Defaulters</Text>
                  <Text style={styles.reportStatValue}>{resultReportStatsNative.totalDefaulters}</Text>
                </View>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Calls Done</Text>
                  <Text style={styles.reportStatValue}>{resultReportStatsNative.callsDone}</Text>
                </View>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Not Received</Text>
                  <Text style={styles.reportStatValue}>{resultReportStatsNative.notReceived}</Text>
                </View>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Pre-informed</Text>
                  <Text style={styles.reportStatValue}>{resultReportStatsNative.preInformed}</Text>
                </View>
                <View style={styles.reportStatCard}>
                  <Text style={styles.reportStatLabel}>Avg Duration</Text>
                  <Text style={styles.reportStatValue}>{resultReportStatsNative.avgDuration}m</Text>
                </View>
              </View>
              <TouchableOpacity style={styles.applyBtn} onPress={() => copyText(resultReportMessageNative, "Result report")}>
                <Text style={styles.applyBtnText}>Copy WhatsApp Report</Text>
              </TouchableOpacity>
              <View style={styles.reportPreviewBox}>
                <Text style={styles.reportPreviewText}>{resultReportMessageNative}</Text>
              </View>
              <View style={styles.filterRow}>
                <TouchableOpacity style={[styles.filterBtn, resultReportFilter === "all" && styles.filterBtnActive]} onPress={() => setResultReportFilter("all")}>
                  <Text style={[styles.filterBtnText, resultReportFilter === "all" && styles.filterBtnTextActive]}>All</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, resultReportFilter === "completed" && styles.filterBtnActive]} onPress={() => setResultReportFilter("completed")}>
                  <Text style={[styles.filterBtnText, resultReportFilter === "completed" && styles.filterBtnTextActive]}>Completed</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.filterBtn, resultReportFilter === "pending" && styles.filterBtnActive]} onPress={() => setResultReportFilter("pending")}>
                  <Text style={[styles.filterBtnText, resultReportFilter === "pending" && styles.filterBtnTextActive]}>Pending</Text>
                </TouchableOpacity>
              </View>
              <FlatList
                data={pagedResultReportRows}
                keyExtractor={(r, idx) => `${r.mentor}-${idx}`}
                initialNumToRender={12}
                windowSize={8}
                refreshing={resultReportRefreshing}
                onRefresh={() => refreshResultReport(true)}
                renderItem={({ item }) => (
                  <View style={styles.studentCard}>
                    <Text style={styles.studentName}>{item.mentor}</Text>
                    <Text style={styles.studentMeta}>
                      Need: {item.need_call} | Done: {item.done} | Pending: {item.not_done}
                    </Text>
                    <Text style={styles.studentMeta}>
                      Received: {item.received} | Not Received: {item.not_received} | Msg: {item.msg_sent}
                    </Text>
                    <Text style={[styles.studentMeta, Number(item.completion_percent) < 100 && styles.lowText]}>
                      Completion: {item.completion_percent}%
                    </Text>
                  </View>
                )}
              />
              {pagedResultReportRows.length < filteredResultReportRows.length ? (
                <TouchableOpacity style={styles.loadMoreBtn} onPress={() => setResultReportVisible((n) => n + PAGE_SIZE)}>
                  <Text style={styles.loadMoreText}>Load More</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          )
        ) : activeTab === "control" ? (
          !staffToken ? (
            <View style={styles.infoPanel}>
              <Text style={styles.infoTitle}>Native Control Login</Text>
              <TextInput
                value={staffUser}
                onChangeText={setStaffUser}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Username"
                style={styles.serverInput}
              />
              <TextInput
                value={staffPass}
                onChangeText={setStaffPass}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Password"
                secureTextEntry
                style={[styles.serverInput, { marginTop: 8 }]}
              />
              <TouchableOpacity style={styles.applyBtn} onPress={doStaffLogin} disabled={staffLoading}>
                <Text style={styles.applyBtnText}>{staffLoading ? "Please wait..." : "Login"}</Text>
              </TouchableOpacity>
            </View>
          ) : (
            <View style={styles.studentsWrap}>
              <Text style={styles.infoTitle}>Control Summary</Text>
              <View style={styles.syncRow}>
                <Text style={styles.syncText}>{formatSync(lastSync.control)}</Text>
                <TouchableOpacity
                  style={styles.syncBtn}
                  onPress={async () => {
                    await refreshControlSummary();
                    showToast("Synced");
                  }}
                  disabled={staffLoading}
                >
                  <Text style={styles.syncBtnText}>Sync now</Text>
                </TouchableOpacity>
              </View>
              <FlatList
                horizontal
                showsHorizontalScrollIndicator={false}
                data={staffModules}
                keyExtractor={(m) => String(m.module_id)}
                style={{ maxHeight: 44, marginBottom: 8 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[
                      styles.moduleChip,
                      staffModuleId === item.module_id && styles.moduleChipActive,
                    ]}
                    onPress={() => setStaffModuleId(item.module_id)}
                  >
                    <Text
                      style={[
                        styles.moduleChipText,
                        staffModuleId === item.module_id && styles.moduleChipTextActive,
                      ]}
                    >
                      {item.name}
                    </Text>
                  </TouchableOpacity>
                )}
              />
              <FlatList
                horizontal
                showsHorizontalScrollIndicator={false}
                data={staffWeeks}
                keyExtractor={(w, idx) => `${w}-${idx}`}
                style={{ maxHeight: 44, marginBottom: 8 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={[styles.moduleChip, staffWeek === item && styles.moduleChipActive]}
                    onPress={() => setStaffWeek(item)}
                  >
                    <Text style={[styles.moduleChipText, staffWeek === item && styles.moduleChipTextActive]}>
                      Week {item}
                    </Text>
                  </TouchableOpacity>
                )}
              />
              <Text style={styles.studentMeta}>Attendance Week: {staffControl.week ?? "-"}</Text>
              <Text style={[styles.infoTitle, { fontSize: 15, marginTop: 8 }]}>Attendance Mentor-wise</Text>
              <FlatList
                data={staffControl.attendance}
                keyExtractor={(r, idx) => `${r.mentor}-${idx}`}
                renderItem={({ item }) => (
                  <View style={styles.studentCard}>
                    <Text style={styles.studentName}>{item.mentor}</Text>
                    <Text style={styles.studentMeta}>
                      Students: {item.students} | Need: {item.need_call} | Done: {item.done} | Pending: {item.not_done}
                    </Text>
                    <Text style={[styles.studentMeta, item.completion_percent < 100 && styles.lowText]}>
                      Completion: {item.completion_percent}%
                    </Text>
                  </View>
                )}
              />
              <Text style={[styles.infoTitle, { fontSize: 15, marginTop: 8 }]}>
                Result Mentor-wise {staffControl.result_upload ? `(${staffControl.result_upload.test_name}-${staffControl.result_upload.subject_name})` : ""}
              </Text>
              <FlatList
                data={staffControl.result}
                keyExtractor={(r, idx) => `${r.mentor}-${idx}`}
                renderItem={({ item }) => (
                  <View style={styles.studentCard}>
                    <Text style={styles.studentName}>{item.mentor}</Text>
                    <Text style={styles.studentMeta}>
                      Need: {item.need_call} | Done: {item.done} | Pending: {item.not_done}
                    </Text>
                    <Text style={[styles.studentMeta, item.completion_percent < 100 && styles.lowText]}>
                      Completion: {item.completion_percent}%
                    </Text>
                  </View>
                )}
              />
            </View>
          )
        ) : activeTab !== "settings" ? (
          <WebView
            key={`${activeTab}-${reloadKey}`}
            source={{ uri: targetUrl }}
            style={styles.webview}
            sharedCookiesEnabled
            javaScriptEnabled
            domStorageEnabled
            startInLoadingState
            injectedJavaScript={injectedCss}
          />
        ) : (
          <View style={styles.infoPanel}>
            <Text style={styles.infoTitle}>Server</Text>
            <Text style={styles.infoText}>{LIVE_API_BASE_URL}</Text>
            <TouchableOpacity
              style={[styles.applyBtn, { backgroundColor: "#0f4d8a", marginTop: 8 }]}
              onPress={() => setReloadKey((k) => k + 1)}
            >
              <Text style={styles.applyBtnText}>Reload Current Tab</Text>
            </TouchableOpacity>
            <Text style={[styles.infoTitle, { marginTop: 14 }]}>Quick Guide</Text>
            <Text style={styles.infoText}>1. Open any tab and login once.</Text>
            <Text style={styles.infoText}>2. Session is shared across tabs.</Text>
            <Text style={styles.infoText}>3. Use module dropdown as needed.</Text>
            <Text style={styles.infoText}>4. Use Switch to return role selector.</Text>
          </View>
        )}
      </View>

      <View style={[styles.bottomTabs, { backgroundColor: palette.tabBarBg, borderTopColor: palette.tabBarBorder }]}>
        {roleTabs.map((t) => (
          <TabButton
            key={t.key}
            label={t.label}
            active={activeTab === t.key}
            onPress={() => setActiveTab(t.key)}
            palette={palette}
          />
        ))}
      </View>
      <Modal
        visible={headerMenuOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setHeaderMenuOpen(false)}
      >
        <View style={styles.headerMenuOverlay}>
          <TouchableOpacity style={styles.headerMenuBackdrop} onPress={() => setHeaderMenuOpen(false)} />
          <View style={styles.headerMenuCard}>
            <TouchableOpacity
              style={styles.headerMenuItem}
              onPress={() => {
                setHeaderMenuOpen(false);
                toggleTheme();
              }}
            >
              <Text style={styles.headerMenuItemText}>{isDark ? "Switch to Light Mode" : "Switch to Dark Mode"}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.headerMenuItem}
              onPress={() => {
                setHeaderMenuOpen(false);
                onExit();
              }}
            >
              <Text style={[styles.headerMenuItemText, { color: APP_COLORS.danger }]}>Logout</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
      {toastVisible ? (
        <View style={styles.toastWrap}>
          <Text style={styles.toastText}>{toastMsg}</Text>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

function TabButton({ label, active, onPress, palette }) {
  return (
    <TouchableOpacity
      style={[styles.tabBtn, active && styles.tabBtnActive, active && { backgroundColor: palette.tabActiveBg }]}
      onPress={onPress}
    >
      <Text
        style={[
          styles.tabText,
          { color: palette.tabText },
          active && styles.tabTextActive,
          active && { color: palette.tabActiveText },
        ]}
      >
        {label}
      </Text>
    </TouchableOpacity>
  );
}

export default function App() {
  const [selectedRole, setSelectedRole] = useState("");
  const [booting, setBooting] = useState(true);
  const [showSplash, setShowSplash] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);

  useEffect(() => {
    (async () => {
      setApiBaseUrl(LIVE_API_BASE_URL);
      await AsyncStorage.setItem(LEGACY_MENTOR_BASE_KEY, LIVE_API_BASE_URL);
      const savedRole = await AsyncStorage.getItem(ROLE_KEY);
      if (savedRole) {
        const [staffSession, mentorSession] = await Promise.all([
          AsyncStorage.getItem(STAFF_SESSION_KEY),
          AsyncStorage.getItem(MENTOR_SESSION_KEY),
        ]);
        if (savedRole === "mentor" && mentorSession) {
          setSelectedRole("mentor");
        } else if ((savedRole === "coordinator" || savedRole === "superadmin") && staffSession) {
          setSelectedRole(savedRole);
        }
      }
      setBooting(false);
    })();
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => setShowSplash(false), 1100);
    return () => clearTimeout(timer);
  }, []);

  const clearRole = async () => {
    setSelectedRole("");
    setUsername("");
    setPassword("");
    await AsyncStorage.removeItem(ROLE_KEY);
    await AsyncStorage.removeItem(STAFF_SESSION_KEY);
    await AsyncStorage.removeItem(MENTOR_SESSION_KEY);
  };

  const doUnifiedLogin = async () => {
    const user = username.trim();
    const pass = password;
    if (!user || !pass) {
      Alert.alert("Required", "Username and password are required.");
      return;
    }
    setLoginLoading(true);
    try {
      setApiBaseUrl(LIVE_API_BASE_URL);
      await AsyncStorage.setItem(LEGACY_MENTOR_BASE_KEY, LIVE_API_BASE_URL);

      try {
        const staff = await staffLogin(user, pass);
        const role = staff.role === "superadmin" ? "superadmin" : "coordinator";
        await AsyncStorage.setItem(
          STAFF_SESSION_KEY,
          JSON.stringify({ role, username: user, token: staff.token })
        );
        await AsyncStorage.setItem(ROLE_KEY, role);
        setSelectedRole(role);
        return;
      } catch (_) {}

      const mentor = await login(user, pass);
      await AsyncStorage.setItem(
        MENTOR_SESSION_KEY,
        JSON.stringify({ token: mentor.token, mentorName: mentor.mentor })
      );
      await AsyncStorage.setItem(ROLE_KEY, "mentor");
      setSelectedRole("mentor");
    } catch (err) {
      Alert.alert("Login failed", String(err.message || err));
    } finally {
      setLoginLoading(false);
    }
  };

  if (booting) {
    return (
      <SafeAreaView style={styles.gatewayPage}>
        <StatusBar barStyle="light-content" backgroundColor={APP_COLORS.primary} />
      </SafeAreaView>
    );
  }

  if (showSplash) {
    return (
      <SafeAreaView style={styles.gatewayPage}>
        <StatusBar barStyle="light-content" backgroundColor={APP_COLORS.primary} />
        <View style={styles.splashCardCenter}>
          <Image source={{ uri: "https://easymentor-web.onrender.com/static/logo.png" }} style={styles.splashLogo} />
          <Text style={styles.splashTitle}>EasyMentor Mobile</Text>
          <Text style={styles.splashSub}>Attendance Follow-up ERP</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!selectedRole) {
    return (
      <UnifiedLoginScreen
        loading={loginLoading}
        username={username}
        password={password}
        onUsername={setUsername}
        onPassword={setPassword}
        onLogin={doUnifiedLogin}
      />
    );
  }

  if (selectedRole === "mentor") {
    return <LegacyMentorApp key="mentor-live" onExitApp={clearRole} />;
  }

  return (
    <RoleWebTabsApp
      role={selectedRole}
      apiBaseUrl={LIVE_API_BASE_URL}
      onChangeBase={() => {}}
      onExit={clearRole}
    />
  );
}

const styles = StyleSheet.create({
  gatewayPage: {
    flex: 1,
    backgroundColor: APP_COLORS.bg,
    paddingTop: Platform.OS === "android" ? APP_DS.s16 : APP_DS.s8,
    paddingHorizontal: APP_DS.s16,
  },
  gatewayHeader: {
    backgroundColor: APP_COLORS.primary,
    borderRadius: 14,
    padding: 16,
    marginTop: 8,
    marginBottom: 14,
  },
  gatewayTitle: {
    color: "#fff",
    fontSize: 24,
    fontWeight: "800",
  },
  gatewaySub: {
    color: "#d9e8fb",
    marginTop: 4,
  },
  splashCardCenter: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: APP_DS.s16,
  },
  splashCard: {
    backgroundColor: APP_COLORS.primary,
    borderRadius: APP_DS.radiusCard,
    padding: APP_DS.s16,
    marginTop: APP_DS.s8,
    marginBottom: APP_DS.s16,
    alignItems: "center",
  },
  splashLogo: {
    width: 70,
    height: 70,
    marginBottom: 10,
    borderRadius: 35,
    backgroundColor: "#fff",
  },
  splashTitle: {
    color: "#fff",
    fontSize: 22,
    fontWeight: "800",
    lineHeight: 28,
  },
  splashSub: {
    color: "#d9e8fb",
    marginTop: 4,
    textAlign: "center",
  },
  gatewayCard: {
    backgroundColor: APP_COLORS.card,
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: APP_DS.radiusCard,
    padding: APP_DS.s16,
    marginBottom: APP_DS.s16,
    shadowColor: "#0f172a",
    shadowOpacity: 0.08,
    shadowOffset: { width: 0, height: 4 },
    shadowRadius: 10,
    elevation: 2,
  },
  gatewaySection: {
    color: APP_COLORS.text,
    fontWeight: "700",
    fontSize: 22,
    marginBottom: APP_DS.s8,
    lineHeight: 28,
  },
  serverRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: 8,
  },
  serverChip: {
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
    backgroundColor: "#fff",
  },
  serverChipActive: {
    backgroundColor: APP_COLORS.primary,
    borderColor: APP_COLORS.primary,
  },
  serverChipText: {
    color: APP_COLORS.primary,
    fontWeight: "700",
  },
  serverChipTextActive: {
    color: "#fff",
  },
  serverInput: {
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: APP_DS.radiusInput,
    paddingVertical: 12,
    paddingHorizontal: 12,
    color: APP_COLORS.text,
    backgroundColor: "#fff",
    fontSize: 16,
  },
  roleButton: {
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
    backgroundColor: "#fff",
  },
  roleTitle: {
    color: APP_COLORS.primaryDark,
    fontWeight: "800",
    fontSize: 16,
  },
  roleDesc: {
    color: APP_COLORS.muted,
    marginTop: 3,
  },
  featureBullet: {
    color: APP_COLORS.muted,
    marginBottom: 6,
    lineHeight: 24,
    fontSize: 16,
  },
  portalPage: {
    flex: 1,
    backgroundColor: APP_COLORS.bg,
  },
  portalHeader: {
    backgroundColor: APP_COLORS.primary,
    paddingHorizontal: APP_DS.s16,
    paddingTop: Platform.OS === "android" ? APP_DS.s16 : APP_DS.s8,
    paddingBottom: APP_DS.s16,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  portalTitle: {
    color: "#fff",
    fontSize: 22,
    fontWeight: "800",
    lineHeight: 28,
  },
  portalSub: {
    color: "#d8e9fc",
    fontSize: 14,
    marginTop: 2,
  },
  exitBtn: {
    backgroundColor: "#ffffff",
    borderRadius: APP_DS.radiusBtn,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  exitBtnText: {
    color: APP_COLORS.primary,
    fontWeight: "700",
  },
  overflowButton: {
    width: 40,
    height: 40,
    borderRadius: APP_DS.radiusBtn,
    borderWidth: 1,
    borderColor: "#c7d3e8",
    backgroundColor: "#ffffff",
    alignItems: "center",
    justifyContent: "center",
  },
  overflowButtonText: {
    fontSize: 20,
    lineHeight: 22,
    color: APP_COLORS.primaryDark,
    fontWeight: "800",
  },
  headerMenuOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.25)",
    justifyContent: "flex-start",
    alignItems: "flex-end",
    paddingTop: Platform.OS === "android" ? APP_DS.s32 + 48 : APP_DS.s32 + 36,
    paddingRight: APP_DS.s16,
  },
  headerMenuBackdrop: {
    ...StyleSheet.absoluteFillObject,
  },
  headerMenuCard: {
    minWidth: 220,
    borderRadius: APP_DS.radiusCard,
    borderWidth: 1,
    borderColor: APP_COLORS.border,
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
    fontSize: 16,
    fontWeight: "600",
    color: APP_COLORS.text,
  },
  portalBody: {
    flex: 1,
    backgroundColor: APP_COLORS.bg,
  },
  submenuBar: {
    backgroundColor: "#f4f8ff",
    borderBottomWidth: 1,
    borderBottomColor: APP_COLORS.border,
    maxHeight: 56,
  },
  submenuContent: {
    paddingHorizontal: 8,
    paddingVertical: 8,
    alignItems: "center",
  },
  submenuChip: {
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginRight: 8,
    backgroundColor: "#fff",
  },
  submenuChipActive: {
    backgroundColor: APP_COLORS.primary,
    borderColor: APP_COLORS.primary,
  },
  submenuChipText: {
    color: APP_COLORS.primary,
    fontSize: 12,
    fontWeight: "700",
  },
  submenuChipTextActive: {
    color: "#fff",
  },
  webview: {
    flex: 1,
    backgroundColor: APP_COLORS.bg,
  },
  infoPanel: {
    margin: APP_DS.s16,
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: APP_DS.radiusCard,
    padding: APP_DS.s16,
  },
  infoTitle: {
    color: APP_COLORS.text,
    fontWeight: "800",
    fontSize: 18,
    marginBottom: APP_DS.s8,
  },
  infoText: {
    color: APP_COLORS.muted,
    marginBottom: 6,
    fontSize: 16,
    lineHeight: 22,
  },
  applyBtn: {
    marginTop: APP_DS.s8,
    backgroundColor: APP_COLORS.accent,
    borderRadius: APP_DS.radiusBtn,
    minHeight: 48,
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  applyBtnText: {
    color: "#fff",
    fontWeight: "700",
  },
  bottomTabs: {
    flexDirection: "row",
    borderTopWidth: 1,
    borderTopColor: APP_COLORS.border,
    backgroundColor: "#fff",
    paddingHorizontal: APP_DS.s8,
    paddingVertical: APP_DS.s8,
  },
  tabBtn: {
    flex: 1,
    borderRadius: APP_DS.radiusBtn,
    paddingVertical: 12,
    alignItems: "center",
    marginHorizontal: 2,
  },
  tabBtnActive: {
    backgroundColor: "#e8f2ff",
  },
  tabText: {
    color: APP_COLORS.muted,
    fontWeight: "700",
    fontSize: 14,
  },
  tabTextActive: {
    color: APP_COLORS.primary,
  },
  studentsWrap: {
    flex: 1,
    padding: 10,
  },
  studentsTopRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  smallDanger: {
    backgroundColor: "#c62828",
    borderRadius: 8,
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  smallDangerText: {
    color: "#fff",
    fontWeight: "700",
    fontSize: 12,
  },
  moduleChip: {
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginRight: 6,
    backgroundColor: "#fff",
  },
  moduleChipActive: {
    backgroundColor: APP_COLORS.primary,
    borderColor: APP_COLORS.primary,
  },
  moduleChipText: {
    color: APP_COLORS.primary,
    fontSize: 12,
    fontWeight: "700",
  },
  moduleChipTextActive: {
    color: "#fff",
  },
  studentCard: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: APP_DS.radiusCard,
    padding: APP_DS.s16,
    marginBottom: APP_DS.s16,
    shadowColor: "#0f172a",
    shadowOpacity: 0.08,
    shadowOffset: { width: 0, height: 4 },
    shadowRadius: 10,
    elevation: 2,
  },
  studentName: {
    color: APP_COLORS.text,
    fontWeight: "700",
    fontSize: 18,
  },
  studentMeta: {
    color: APP_COLORS.muted,
    marginTop: 2,
    fontSize: 14,
  },
  syncText: {
    color: APP_COLORS.muted,
    fontSize: 12,
    marginBottom: 0,
    flex: 1,
  },
  syncRow: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 8,
  },
  syncBtn: {
    backgroundColor: "#e8f2ff",
    borderWidth: 1,
    borderColor: "#b9d5f5",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginLeft: 8,
  },
  syncBtnText: {
    color: APP_COLORS.primary,
    fontSize: 12,
    fontWeight: "700",
  },
  toastWrap: {
    position: "absolute",
    bottom: 68,
    alignSelf: "center",
    backgroundColor: "#1c8f4f",
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 8,
    shadowColor: "#000",
    shadowOpacity: 0.2,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
  toastText: {
    color: "#fff",
    fontSize: 13,
    fontWeight: "700",
  },
  listFooter: {
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  listEndText: {
    textAlign: "center",
    color: APP_COLORS.muted,
    fontSize: 12,
    paddingVertical: 10,
  },
  skeletonCard: {
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: 10,
    padding: 10,
    marginBottom: 8,
  },
  skeletonLine: {
    height: 10,
    backgroundColor: "#e6edf6",
    borderRadius: 6,
    marginBottom: 8,
  },
  actionRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginBottom: 8,
    alignItems: "center",
  },
  smallBtn: {
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    backgroundColor: "#fff",
    marginRight: 6,
    marginBottom: 6,
  },
  smallBtnText: {
    color: APP_COLORS.text,
    fontSize: 12,
    maxWidth: 160,
  },
  smallBtnPrimary: {
    backgroundColor: APP_COLORS.primary,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    marginRight: 6,
    marginBottom: 6,
  },
  smallBtnPrimaryText: {
    color: "#fff",
    fontWeight: "700",
    fontSize: 12,
  },
  uploadMsg: {
    color: APP_COLORS.primaryDark,
    marginBottom: 8,
    fontSize: 12,
  },
  statsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
  },
  reportStatsGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
    marginBottom: APP_DS.s16,
    marginTop: APP_DS.s8,
    gap: APP_DS.s8,
  },
  reportStatCard: {
    width: "48%",
    backgroundColor: "#f8fbff",
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: APP_DS.radiusBtn,
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  reportStatLabel: {
    color: APP_COLORS.muted,
    fontSize: 12,
  },
  reportStatValue: {
    color: APP_COLORS.text,
    fontSize: 18,
    fontWeight: "800",
    marginTop: 2,
  },
  reportPreviewBox: {
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: APP_DS.radiusBtn,
    backgroundColor: "#f8fbff",
    padding: 12,
    marginTop: APP_DS.s8,
    marginBottom: APP_DS.s8,
  },
  reportPreviewText: {
    color: APP_COLORS.muted,
    fontSize: 14,
    lineHeight: 20,
  },
  statCard: {
    width: "48%",
    backgroundColor: "#fff",
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: APP_DS.radiusCard,
    padding: APP_DS.s16,
    marginBottom: APP_DS.s8,
  },
  statLabel: {
    color: APP_COLORS.muted,
    fontSize: 14,
  },
  statValue: {
    color: APP_COLORS.primaryDark,
    fontWeight: "800",
    fontSize: 22,
    marginTop: 3,
  },
  loadMoreBtn: {
    alignSelf: "center",
    borderWidth: 1,
    borderColor: APP_COLORS.primary,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
    marginTop: 6,
    marginBottom: 8,
    backgroundColor: "#fff",
  },
  loadMoreText: {
    color: APP_COLORS.primary,
    fontWeight: "700",
    fontSize: 12,
  },
  lowText: {
    color: "#c62828",
    fontWeight: "700",
  },
  filterRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginBottom: 8,
  },
  filterBtn: {
    borderWidth: 1,
    borderColor: APP_COLORS.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginRight: 6,
    marginBottom: 6,
    backgroundColor: "#fff",
  },
  filterBtnActive: {
    backgroundColor: APP_COLORS.primary,
    borderColor: APP_COLORS.primary,
  },
  filterBtnText: {
    color: APP_COLORS.primary,
    fontSize: 12,
    fontWeight: "700",
  },
  filterBtnTextActive: {
    color: "#fff",
  },
});
