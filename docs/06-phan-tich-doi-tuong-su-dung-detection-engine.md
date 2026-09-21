# PHÂN TÍCH ĐỐI TƯỢNG SỬ DỤNG - DETECTION ENGINE

> **Phiên bản:** 3.3  
> **Ngày:** 2026-09-13  
> **Trạng thái:** Hoàn thành thiết kế

---

## 1. MỤC ĐÍCH

Tài liệu này phân tích các đối tượng sử dụng (Actors) và mối quan hệ của họ với **Detection Engine** trong hệ thống Sentinel Auth.

---

## 2. TỔNG QUAN ACTORS

| Actor | Vai trò | Tương tác chính |
|-------|---------|------------------|
| **SOC Analyst** | Giám sát và điều tra alerts | Xem dashboard, tiếp nhận alert, phân loại |
| **Security Manager** | Quản lý cấp cao | Review escalated alerts, báo cáo |
| **Core App** | Hệ thống internal | Gửi LoginEvent, nhận Action |
| **ML Service** | Hệ thống internal | Cung cấp ML inference |

---

## 3. ACTORS CHI TIẾT

### 3.1 SOC Analyst

#### 3.1.1 Thông tin cơ bản

| Thuộc tính | Giá trị |
|------------|---------|
| **Actor ID** | ACT-SOC-01 |
| **Tên** | SOC Analyst |
| **Loại** | Human - Internal |
| **Vai trò** | Chuyên viên giám sát an toàn thông tin |
| **Phòng ban** | Security Operations Center (SOC) |
| **Báo cáo** | Security Manager |

#### 3.1.2 Mô tả

SOC Analyst là nhân viên chịu trách nhiệm giám sát các hoạt động đăng nhập và điều tra các cảnh báo bảo mật. Họ làm việc theo ca và sử dụng SOC Dashboard để:

- Theo dõi các alert mới
- Tiếp nhận và điều tra incidents
- Phân loại alerts (true positive / false positive)
- Yêu cầu hành động bảo vệ khi cần thiết

#### 3.1.3 Quyền hạn

| Quyền | Mô tả | Use Cases |
|-------|-------|-----------|
| `VIEW_DASHBOARD` | Xem SOC Dashboard | UC-DE-08 |
| `VIEW_ALERTS` | Xem danh sách alerts | UC-DE-08, UC-DE-09 |
| `ACKNOWLEDGE_ALERT` | Tiếp nhận alert | UC-DE-09 |
| `INVESTIGATE_ALERT` | Điều tra alert | UC-DE-10 |
| `VIEW_EVIDENCE` | Xem evidence | UC-DE-11 |
| `RESOLVE_ALERT` | Phân loại và đóng alert | UC-DE-12 |
| `REQUEST_ACTION` | Yêu cầu action | UC-DE-13 |
| `SEARCH_HISTORY` | Tra cứu login history | UC-DE-14 |

#### 3.1.4 Quy trình công việc

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SOC ANALYST WORKFLOW                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐     ┌──────────────┐     ┌──────────────┐                 │
│  │ Nhận     │────►│ Tiếp nhận    │────►│ Điều tra     │                 │
│  │ Alert    │     │ Alert        │     │ Alert        │                 │
│  └──────────┘     └──────────────┘     └──────┬───────┘                 │
│                                                  │                          │
│                           ┌───────────────────────┼───────────────────────┐ │
│                           │                       │                       │ │
│                           ▼                       ▼                       ▼ │
│                    ┌──────────────┐     ┌──────────────┐     ┌───────────┐ │
│                    │ Xác định     │     │ Đánh dấu     │     │ Không    │ │
│                    │ True Positive │     │ False Positive│     │ rõ ràng  │ │
│                    └───────┬──────┘     └──────────────┘     └─────┬─────┘ │
│                            │                                      │        │
│                            ▼                                      ▼        │
│                    ┌──────────────┐                         ┌──────────┐  │
│                    │ Yêu cầu      │                         │Escalate  │  │
│                    │ Action       │                         │          │  │
│                    └───────┬──────┘                         └──────────┘  │
│                            │                                                │
│                            ▼                                                │
│                    ┌──────────────┐                                         │
│                    │ Đóng Alert   │                                         │
│                    │ (Resolved)   │                                         │
│                    └──────────────┘                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 3.1.5 KPI/Metrics

| Metric | Target | Mô tả |
|--------|--------|-------|
| Alert Response Time | < 15 phút | Thời gian từ alert created → acknowledged |
| Investigation Time | < 30 phút | Thời gian điều tra trung bình |
| Resolution Rate | > 80% | Tỷ lệ alert được resolved trong ngày |
| False Positive Rate | < 20% | Tỷ lệ false positive |

#### 3.1.6 Profile Data

```json
{
  "id": "UUID",
  "user_id": "UUID (FK to users)",
  "display_name": "Nguyễn Văn A",
  "email": "soc.analyst@company.com",
  "is_active": true,
  "max_alerts": 10,
  "shift_pattern": "morning|afternoon|night",
  "created_at": "TIMESTAMPTZ"
}
```

---

### 3.2 Security Manager

#### 3.2.1 Thông tin cơ bản

| Thuộc tính | Giá trị |
|------------|---------|
| **Actor ID** | ACT-MGR-01 |
| **Tên** | Security Manager |
| **Loại** | Human - Internal |
| **Vai trò** | Quản lý an toàn thông tin |
| **Phòng ban** | Information Security |
| **Báo cáo** | C-Level / Board |

#### 3.2.2 Mô tả

Security Manager là người quản lý đội ngũ SOC và chịu trách nhiệm:

- Giám sát tổng thể tình hình an ninh
- Review các alerts được escalated
- Phê duyệt các action quan trọng
- Báo cáo định kỳ cho ban lãnh đạo
- Điều chỉnh policies nếu cần

#### 3.2.3 Quyền hạn

| Quyền | Mô tả | Use Cases |
|-------|-------|-----------|
| `VIEW_MANAGER_DASHBOARD` | Xem dashboard quản lý | UC-DE-08 (extended) |
| `VIEW_ALL_ALERTS` | Xem tất cả alerts | UC-DE-08 |
| `REVIEW_ESCALATED` | Review escalated alerts | UC-DE-12 |
| `APPROVE_ACTION` | Phê duyệt action quan trọng | UC-DE-13 |
| `MANAGE_POLICIES` | Quản lý policies | UC-DE-15 |
| `MANAGE_SOC_TEAM` | Quản lý team SOC | (Core App) |
| `VIEW_REPORTS` | Xem báo cáo | UC-M-02 |

#### 3.2.4 Quy trình Escalation

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ SOC Analyst │────►│   Review    │────►│  Security   │
│ Escalates   │     │   Request   │     │  Manager    │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
                           ┌─────────────────────┼─────────────────────┐
                           │                     │                     │
                           ▼                     ▼                     ▼
                    ┌─────────────┐       ┌─────────────┐      ┌────────────┐
                    │  Approve    │       │   Reject    │      │  Delegate  │
                    │  Escalation │       │  Escalation │      │  to other  │
                    └─────────────┘       └─────────────┘      └────────────┘
```

---

### 3.3 Core App (System Actor)

#### 3.3.1 Thông tin cơ bản

| Thuộc tính | Giá trị |
|------------|---------|
| **Actor ID** | ACT-SYS-01 |
| **Tên** | Core App |
| **Loại** | System - Internal Service |
| **Protocol** | HTTP REST |

#### 3.3.2 Mô tả

Core App là service chính xử lý authentication. Nó giao tiếp với Detection Engine qua:

- **Gửi:** LoginEvent (sau mỗi login attempt)
- **Nhận:** Action requests (REQUIRE_MFA, LOCK_USER, etc.)

#### 3.3.3 Giao tiếp

**Gửi LoginEvent:**
```json
POST /internal/login-events
{
  "event_id": "UUID",
  "user_id": "UUID | null",
  "username_attempted": "string",
  "outcome": "success | failed",
  "mfa_used": "boolean",
  "ip_address": "string",
  "user_agent": "string",
  "timestamp": "ISO 8601"
}
```

**Nhận Action:**
```json
POST /internal/actions
{
  "action": "REQUIRE_MFA | REVOKE_SESSIONS | LOCK_USER | RATE_LIMIT_IP",
  "target": {
    "type": "user_id | ip_address",
    "value": "UUID | string"
  },
  "reason": "string",
  "risk_level": "string",
  "login_attempt_id": "UUID"
}
```

---

### 3.4 ML Service (System Actor)

#### 3.4.1 Thông tin cơ bản

| Thuộc tính | Giá trị |
|------------|---------|
| **Actor ID** | ACT-SYS-02 |
| **Tên** | ML Service |
| **Loại** | System - Internal Service |
| **Protocol** | HTTP REST |

#### 3.4.2 Mô tả

ML Service cung cấp anomaly detection sử dụng Isolation Forest model. Detection Engine gọi ML Service để:

- Nhận 6 features từ login event
- Trả về normalized anomaly score
- Cung cấp reason codes

#### 3.4.3 Giao tiếp

**Gửi ML Request:**
```json
POST /internal/score
{
  "request_id": "UUID",
  "features": {
    "hour_of_day": 14,
    "fail_count_24h": 2,
    "ip_change_rate_7d": 0.15,
    "new_device": true,
    "average_login_interval_seconds": 28800,
    "deviation_score": 0.3
  }
}
```

**Nhận ML Response:**
```json
{
  "request_id": "UUID",
  "normalized_anomaly_score": 0.72,
  "is_anomaly": true,
  "model_version": "v1.0-isolation-forest",
  "reason_codes": ["unusual_time", "new_device"],
  "model_status": "ready"
}
```

---

## 4. MA TRẬN ACTOR - USE CASE

| Actor | UC-DE-08 | UC-DE-09 | UC-DE-10 | UC-DE-11 | UC-DE-12 | UC-DE-13 | UC-DE-14 | UC-DE-15 |
|-------|----------|----------|----------|----------|----------|----------|----------|----------|
| **SOC Analyst** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Security Manager** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Core App** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

| Actor | UC-DE-01 | UC-DE-02 | UC-DE-03 | UC-DE-04 | UC-DE-05 | UC-DE-06 | UC-DE-07 |
|-------|----------|----------|----------|----------|----------|----------|----------|
| **Core App** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (nhận) |
| **ML Service** | ❌ | ❌ | ✅ (nhận) | ❌ | ❌ | ❌ | ❌ |

---

## 5. USER STORY MAPPING

### SOC Analyst Stories

#### US-SOC-01: Nhận Alert mới
```
As a SOC Analyst
I want to be notified of new high-risk alerts
So that I can respond quickly to potential security threats
```

**Acceptance Criteria:**
- Alert xuất hiện trên dashboard trong 1 phút sau khi tạo
- Badge hiển thị số alert chưa acknowledged
- Sound/notification alert (configurable)

#### US-SOC-02: Điều tra Alert
```
As a SOC Analyst
I want to see all evidence for an alert
So that I can make an informed decision on the alert
```

**Acceptance Criteria:**
- Có thể xem: login details, risk scores, triggered rules, ML reason codes
- Có thể xem: IP reputation, user history
- Timeline hiển thị đầy đủ actions

#### US-SOC-03: Phân loại Alert
```
As a SOC Analyst
I want to classify alerts as true/false positive
So that the system can learn and reduce false positives
```

**Acceptance Criteria:**
- Phải nhập notes khi phân loại
- Alert được đánh dấu resolution và timestamp
- Feedback được ghi log cho ML training

#### US-SOC-04: Yêu cầu Action
```
As a SOC Analyst
I want to request security actions on suspicious accounts
So that I can protect the organization
```

**Acceptance Criteria:**
- Có thể chọn: LOCK_USER, REVOKE_SESSIONS, BLOCK_IP
- Phải nhập reason
- Action được logged và auditable

---

### Security Manager Stories

#### US-MGR-01: Review Dashboard
```
As a Security Manager
I want to see overall security metrics
So that I can assess the security posture
```

**Acceptance Criteria:**
- Xem trend alerts theo thời gian
- Xem top violation reasons
- Xem team workload distribution

#### US-MGR-02: Review Escalated Cases
```
As a Security Manager
I want to review escalated alerts
So that I can provide guidance or approve actions
```

**Acceptance Criteria:**
- Xem tất cả escalated alerts
- Có thể approve/reject/reassign
- Timeline đầy đủ

#### US-MGR-03: Adjust Detection Policy
```
As a Security Manager
I want to adjust detection thresholds
So that we can balance security and user experience
```

**Acceptance Criteria:**
- Có thể tạo/sửa policies
- Có thể activate/deactivate policies
- Thay đổi được audit logged

---

## 6. ACTOR RELATIONSHIPS

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ACTOR RELATIONSHIP DIAGRAM                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│     ┌─────────────────┐                                                    │
│     │Security Manager │                                                    │
│     │    (ACT-01)     │                                                    │
│     └────────┬────────┘                                                    │
│              │                                                            │
│              │ 1. Manages                                                  │
│              │ 2. Reviews                                                  │
│              ▼                                                            │
│     ┌─────────────────┐      1. Assigned to                                │
│     │   SOC Analyst   │◄──────────────────────┐                           │
│     │    (ACT-02)     │                      │                           │
│     └────────┬────────┘                      │                           │
│              │                               │                           │
│              │ Uses                          │                           │
│              ▼                               │                           │
│     ┌─────────────────────────────────────────────┐│                           │
│     │           DETECTION ENGINE                   ││                           │
│     │                                             ││                           │
│     │  ┌───────────┐  ┌───────────┐  ┌─────────┐  ││                           │
│     │  │Dashboard │  │  Alert    │  │ Policy  │  ││                           │
│     │  │   APIs   │  │   APIs   │  │   APIs  │  ││                           │
│     │  └───────────┘  └───────────┘  └─────────┘  ││                           │
│     └─────────────────────────────────────────────┘│                           │
│                                                     │                           │
│     ┌─────────────────┐      Sends Events           │                           │
│     │    Core App     │────────────────────────────►│                           │
│     │   (ACT-03)      │                            │                           │
│     └─────────────────┘                            │                           │
│                                                     │                           │
│     ┌─────────────────┐      Receives Actions       │                           │
│     │    Core App     │◄────────────────────────────┘                           │
│     └─────────────────┘                               │                           │
│                                                     │                           │
│     ┌─────────────────┐      ML Inference           │                           │
│     │   ML Service    │────────────────────────────►│                           │
│     │   (ACT-04)      │                            │                           │
│     └─────────────────┘                            │                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. PERMISSION MATRIX

| Resource | Action | SOC Analyst | Security Manager | Core App | ML Service |
|----------|--------|------------|------------------|----------|------------|
| **Dashboard** | View | ✅ | ✅ | ❌ | ❌ |
| **Alert** | View | Own/Assigned | All | ❌ | ❌ |
| **Alert** | Acknowledge | ✅ | ✅ | ❌ | ❌ |
| **Alert** | Resolve | ✅ | ✅ | ❌ | ❌ |
| **Alert** | Escalate | ✅ | N/A | ❌ | ❌ |
| **Alert** | Assign | ❌ | ✅ | ❌ | ❌ |
| **Evidence** | View | ✅ | ✅ | ❌ | ❌ |
| **Login History** | Search | ✅ | ✅ | ❌ | ❌ |
| **Login History** | Create | ❌ | ❌ | ✅ | ❌ |
| **Policy** | View | Read-only | ✅ | ❌ | ❌ |
| **Policy** | Create | ❌ | ✅ | ❌ | ❌ |
| **Policy** | Activate | ❌ | ✅ | ❌ | ❌ |
| **Action** | Request | ✅ | ✅ | ❌ | ❌ |
| **ML Score** | Request | ❌ | ❌ | ❌ | N/A |

---

**Document Version:** 3.3  
**Last Updated:** 2026-09-13  
**Status:** ✅ Design Complete
