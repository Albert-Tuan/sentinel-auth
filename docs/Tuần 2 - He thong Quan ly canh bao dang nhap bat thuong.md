# HỆ THỐNG QUẢN LÝ CẢNH BÁO ĐĂNG NHẬP BẤT THƯỜNG

---

## 1. Đối tượng sử dụng phần mềm

| STT | Đối tượng sử dụng | Vai trò |
|-----|-------------------|---------|
| 1 | Người dùng hệ thống (User) | Đăng nhập, xác thực MFA, quản lý session, xác nhận/báo cáo login attempt |
| 2 | SOC Analyst (Chuyên viên SOC) | Giám sát dashboard, tiếp nhận alert, điều tra, phân loại và yêu cầu hành động bảo vệ |
| 3 | Security Administrator (Quản trị viên bảo mật) | Quản lý tài khoản, vai trò, policies, thresholds, audit log |
| 4 | Security Manager (Quản lý an ninh) | Xem dashboard tổng hợp, phê duyệt escalated alerts, xuất báo cáo |

---

## 2. Các chức năng của từng đối tượng

| Đối tượng | Chức năng chính |
|-----------|------------------|
| **Người dùng hệ thống** | • Đăng nhập với username/password |
| | • Xác thực MFA (OTP email/SMS/TOTP) |
| | • Xem và quản lý session hiện tại |
| | • Xác nhận hoặc báo cáo login attempt bất thường |
| | • Quản lý thiết bị tin cậy |
| **SOC Analyst** | • Theo dõi SOC Dashboard (alerts, metrics, trends) |
| | • Tra cứu lịch sử đăng nhập |
| | • Tiếp nhận và điều tra alert |
| | • Xem bằng chứng (Rule/ML scores, reason codes) |
| | • Phân loại alert (Resolved/False Positive/Escalated) |
| | • Yêu cầu hành động bảo vệ (lock user, revoke sessions) |
| | • Đóng hồ sơ incident |
| **Security Administrator** | • Quản lý tài khoản và vai trò người dùng |
| | • Phân quyền truy cập |
| | • Quản lý MFA/Auth Policy |
| | • Quản lý RuleSet và Detection Thresholds |
| | • Cấu hình kênh cảnh báo (email, webhook) |
| | • Quản lý Trust/Block List (IP, device) |
| | • Tra cứu Audit Log |
| | • Quản lý tham số vận hành |
| **Security Manager** | • Xem Dashboard tổng hợp |
| | • Theo dõi alerts Critical/High |
| | • Phê duyệt escalated alerts |
| | • Xuất báo cáo tổng hợp |

---

## 3. Phân quyền người dùng

Hệ thống áp dụng phân quyền theo vai trò (RBAC). Người dùng chỉ được truy cập các chức năng và dữ liệu thuộc phạm vi được cấp.

| Chức năng | User | SOC Analyst | Security Admin | Security Manager |
|-----------|:----:|:-----------:|:--------------:|:----------------:|
| Đăng nhập / Xác thực | ✅ | ✅ | ✅ | ✅ |
| Xem session của mình | ✅ | ❌ | ❌ | ❌ |
| Xem tất cả session | ❌ | ❌ | ✅ | ❌ |
| Xem SOC Dashboard | ❌ | ✅ | ✅ | ✅ |
| Xem tất cả Alerts | ❌ | ✅ | ✅ | ✅ |
| Tiếp nhận Alert | ❌ | ✅ | ✅ | ✅ |
| Điều tra Alert | ❌ | ✅ | ✅ | ✅ |
| Phân loại Alert | ❌ | ✅ | ✅ | ✅ |
| Yêu cầu Action (Lock/Revoke) | ❌ | ✅ | ✅ | ✅ |
| Xem Evidence | ❌ | ✅ | ✅ | ✅ |
| Tra cứu Login History | ❌ | ✅ | ✅ | ✅ |
| Quản lý Policies | ❌ | ❌ | ✅ | ✅ |
| Quản lý Users/Roles | ❌ | ❌ | ✅ | ✅ |
| Quản lý MFA Settings | ❌ | ❌ | ✅ | ✅ |
| Phê duyệt Escalation | ❌ | ❌ | ✅ | ✅ |
| Xem Audit Log | ❌ | ✅ | ✅ | ✅ |
| Xuất báo cáo | ❌ | ❌ | ✅ | ✅ |

---

## 4. Quy trình hoạt động của phần mềm

### 4.1 Quy trình phát hiện và xử lý đăng nhập bất thường

| Bước | Hoạt động | Kết quả |
|------|------------|---------|
| 1 | User đăng nhập vào Core App | Core App xác thực credentials |
| 2 | Core App hỏi Detection trước khi cấp token | `pre-token-check`, timeout 3s, **fail open** |
| 3 | Core App gửi LoginEvent đến Detection Engine | Event được lưu vào login_attempts |
| 4 | Detection Engine xây dựng 6 ML features | Features: hour_of_day, fail_count_24h, ip_change_rate_7d, new_device, avg_login_interval, deviation_score |
| 5 | Detection Engine gọi ML Service | Nhận normalized_anomaly_score và reason_codes |
| 6 | Detection Engine đánh giá Rule Engine | Tính rule_score từ active policy |
| 7 | Detection Engine tính Risk Score | Risk_Score = 0.4 × Rule_Score + 0.6 × ML_Score |
| 8 | Xác định Risk Level và Action | LOW/MEDIUM: Allow, HIGH: Require MFA, CRITICAL: Block + Alert |
| 9 | Tạo Alert (nếu HIGH/CRITICAL) | Alert được gán cho SOC Analyst |
| 10 | Gửi Action về Core App | HIGH → `REQUIRE_MFA`; CRITICAL → `REVOKE_SESSIONS` (không khoá tài khoản) |
| 11 | SOC Analyst tiếp nhận và điều tra | Xem evidence, phân loại alert |
| 12 | Đóng Alert | Resolved/False Positive/Escalated |

### 4.2 Risk Level Thresholds

| Risk Level | Score Range | Action | Mô tả |
|------------|:-----------:|--------|-------|
| LOW | < 0.25 | ALLOW | Đăng nhập bình thường, cấp token ngay |
| MEDIUM | 0.25 - 0.50 | ALLOW_LOG | Cho phép, ghi log cảnh báo, cấp token ngay |
| HIGH | 0.50 - 0.75 | REQUIRE_MFA | **Giữ token**, bắt MFA, thu hồi phiên hiện tại |
| CRITICAL | ≥ 0.75 | BLOCK_ALERT | **Giữ token**, bắt MFA, thu hồi phiên, tạo alert SOC |

> `BLOCK_ALERT` **không** khoá tài khoản. Hành động gửi đi là `REVOKE_SESSIONS` — người
> dùng đăng nhập lại và qua MFA. `LOCK_USER` chỉ dùng thủ công khi SOC đã điều tra có
> bằng chứng. Xem `DECISIONS-DETECTION-v3.3.md` mục 11.2.

---

## 5. Quy trình hoạt động của các chức năng chính

### 5.1 Đăng nhập và Detection Flow

| Chức năng | Quy trình |
|-----------|-----------|
| **Đăng nhập cơ bản** | Nhập username/password → Kiểm tra credentials → Kiểm tra account status (active/locked) → **Hỏi `pre-token-check`** → `low`/`medium` thì tạo session và cấp token → gửi LoginEvent đến Detection Engine |
| **Đăng nhập bị nghi ngờ** | `high`/`critical` → **không tạo session, chưa có token** → phát MFA challenge → qua MFA mới cấp token. Lỗi cổng → fail open, cấp token như bình thường |
| **Detection Processing** | Nhận LoginEvent → Build Features → Gọi ML Service → Evaluate Rules → Calculate Risk Score → Determine Action → Tạo Alert → Gửi Action về Core App (sau khi commit, timeout 3s, nuốt lỗi) |
| **MFA Challenge** | Nhận REQUIRE_MFA action → Tạo MFA transaction → Gửi OTP (email/SMS/TOTP) → User nhập OTP → Xác thực OTP → Tạo session |
| **Risk Action Enforcement** | Nhận action → `REQUIRE_MFA`/`REVOKE_SESSIONS`/`FORCE_LOGOUT`/`LOCK_USER` → đều thu hồi sessions → cập nhật user status (nếu khoá) → ghi audit log |
| **Khôi phục sự cố** | LoginAttempt ở `status='failed'` được `rescore_failed_attempts()` chấm lại. **Chưa có worker gọi định kỳ** — xem `DECISIONS-DETECTION-v3.3.md` mục 12 |

### 5.2 SOC Alert Workflow

| Chức năng | Quy trình |
|-----------|-----------|
| **Tiếp nhận Alert** | Alert được tạo (HIGH/CRITICAL) → Round-robin assign cho SOC Analyst → SOC Analyst xem dashboard → Acknowledge alert |
| **Điều tra Alert** | Xem alert details → Xem login attempt → Xem Risk Assessment (rule + ML scores) → Xem triggered rules → Xem ML reason codes → Kiểm tra IP reputation/user history |
| **Phân loại Alert** | Hoàn thành điều tra → Chọn resolution: Resolved (threat confirmed), False Positive (legitimate login), Escalated (need manager review) → Nhập notes → Update alert status → Ghi timeline |
| **Yêu cầu Action** | Xác định action cần thiết → Chọn: `LOCK_USER`, `REVOKE_SESSIONS`, `REQUIRE_MFA`, `FORCE_LOGOUT` → Nhập reason → Gửi request đến `POST /api/v1/alerts/{id}/actions` → Ghi timeline |

### 5.3 Policy Management

| Chức năng | Quy trình |
|-----------|-----------|
| **Tạo Policy** | Security Admin nhập version, name, rules (JSONB), config (weights, thresholds) → Validate JSONB structure → Lưu với is_active = false |
| **Activate Policy** | Chọn policy → Deactivate all other policies → Set is_active = true → Ghi audit log |
| **Rule Evaluation** | Parse rules từ policy → Với mỗi rule: evaluate condition với features → Nếu triggered: add score × weight → Tính tổng rule_score |

### 5.4 ML Features Building

| Feature | Kiểu | Nguồn/Cách tính |
|---------|------|------------------|
| `hour_of_day` | Integer (0-23) | Trích xuất từ timestamp |
| `fail_count_24h` | Integer (≥0) | Đếm login attempts failed trong 24h |
| `ip_change_rate_7d` | Float (0-1) | Tỷ lệ IP mới trong 7 ngày |
| `new_device` | Boolean | So sánh user_agent với history |
| `avg_login_interval_seconds` | Integer | Trung bình khoảng cách login |
| `deviation_score` | Float (0-1) | Mức lệch so với baseline |

### 5.5 Bảo mật và Audit

| Chức năng | Quy trình |
|-----------|-----------|
| **Xác thực** | Core App xác thực credentials → Detection Engine validate API key → ML Service validate internal token |
| **Audit Logging** | Mọi action đều được ghi vào detection_logs → SOC actions ghi vào alert_timeline → Core actions ghi vào audit_logs |
| **Action Enforcement** | Detection Engine gửi action request → Core App verify request authenticity → Core App enforce action → Core App ghi audit log |
| **Alert Timeline** | Mọi thay đổi trạng thái alert được ghi: created, acknowledged, escalated, resolved, false_positive với actor, timestamp, comment |

---

## 6. Kiến trúc hệ thống

```
┌─────────────────────────────────────────────────────────────────┐
│                     SENTINEL AUTH - ARCHITECTURE                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐      │
│  │    USER     │     │SOC ANALYST  │     │  SEC ADMIN  │      │
│  │   Browser   │     │  Dashboard   │     │   Portal    │      │
│  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘      │
│         │ HTTP/REST          │ HTTP/REST          │ HTTP/REST   │
└─────────┼────────────────────┼────────────────────┼─────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    CORE-APP     │  │DETECTION-ENGINE │  │   ML-SERVICE    │
│  (Port: 8000)   │  │  (Port: 8001)   │  │  (Port: 8002)   │
│                 │  │                 │  │                 │
│ • Auth/Login   │  │ • Rule Engine  │  │ • ML Inference │
│ • MFA/OTP     │  │ • Risk Scoring│  │ • Model Registry│
│ • Session Mgmt│  │ • Alert Mgmt  │  │                 │
│ • User Mgmt   │  │ • SOC Workflow│  │                 │
│                 │  │                 │  │                 │
│ [core-db]      │  │ [detection-db] │  │ [ml-service-db]│
│  13 tables     │  │   7 tables     │  │   3 tables     │
└────────┬────────┘  └────────┬────────┘  └─────────────────┘
         │                    │                    ▲
         │ LoginEvent         │ ML Request          │
         │════════════════════╪════════════════════╝
         │                    │                    │
         │ Action             │ ML Response         │
         │◄══════════════════╪════════════════════│
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    CORE DB      │  │  DETECTION DB   │  │  ML SERVICE DB  │
│  (PostgreSQL)   │  │  (PostgreSQL)   │  │  (PostgreSQL)   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

---

## 7. Database Schema Overview

### 7.1 Core DB (13 tables)

| Bảng | Mô tả |
|------|--------|
| users | Tài khoản người dùng |
| roles | Vai trò (USER, SOC_ANALYST, SECURITY_ADMIN, SECURITY_MANAGER) |
| user_roles | Phân vai trò cho user |
| sessions | JWT tokens, refresh tokens |
| mfa_transactions | MFA challenge lifecycle |
| mfa_notifications | OTP email/SMS tracking |
| audit_logs | Immutable audit trail |
| user_trusted_devices | Remember-me devices |
| ip_addresses | Normalized IP tracking |
| outbox_events | Transactional outbox |
| rate_limits | Rate limiting counters |
| system_settings | Dynamic configuration |
| user_notifications | In-app notifications |

### 7.2 Detection DB (7 tables)

| Bảng | Mô tả |
|------|--------|
| policies | Detection rules (JSONB), weights, thresholds |
| login_attempts | All login events from core-app |
| risk_assessments | Per-attempt scoring (rule + ML) |
| detection_logs | Detailed audit trail |
| soc_analysts | Analyst profiles |
| alerts | SOC alerts (1:N to login_attempts) |
| alert_timeline | SOC action audit trail |

### 7.3 ML Service DB (3 tables)

| Bảng | Mô tả |
|------|--------|
| model_versions | Model registry |
| inference_logs | Inference request/response logging |
| feature_statistics | Data drift monitoring |

---

**Document Version:** 3.3  
**Last Updated:** 2026-09-14  
**Status:** ✅ Design Complete
