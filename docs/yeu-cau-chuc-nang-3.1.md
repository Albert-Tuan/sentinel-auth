# 3.1. Yêu cầu chức năng — Sentinel Auth

Tài liệu này đồng bộ với `PLAN.md`, ADR, OpenAPI và event schema. Các engine nội bộ không được mô hình hóa như actor bên ngoài; chúng là hành vi bên trong hệ thống.

## 3.1.1. Use-case và actor

Sơ đồ tổng quát nằm tại [use-case.puml](use-case.puml). Actor: **User**, **SOC Analyst**, **Security Admin**, **Security Manager** và kênh ngoài **Email/Telegram**.

Nguyên tắc bắt buộc: core-app quyết định đăng nhập đồng bộ; Rule/ML đánh giá login attempt bất đồng bộ sau khi outbox event đã được ghi. Vì vậy ML timeout không thể biến điểm bất thường thành `0` hoặc quyết định cấp token.

## 3.1.2. Đặc tả 26 use-case

### UC-01 — Đăng nhập

- Actor: User. Tiền điều kiện: tài khoản có thể xác thực.
- Luồng chính: core-app rate-limit, kiểm tra credential/account policy và trả `ALLOW`, `MFA_REQUIRED` hoặc `DENY`; trong cùng transaction ghi `LoginAttempt` và `OutboxEvent`.
- Ngoại lệ: lỗi credential, lockout và limit trả thông báo generic; không leak account existence.
- Hậu điều kiện: login attempt bất biến tồn tại; chỉ `ALLOW` mới có session.
- Yêu cầu đặc biệt: Argon2id, không log password, correlation ID, audit security state.

### UC-02 — Thực hiện MFA

- Actor: User. Tiền điều kiện: nhận `MFA_REQUIRED` và pre-auth transaction còn hiệu lực.
- Luồng chính: xác minh WebAuthn/TOTP (email OTP chỉ demo fallback), tạo session sau khi pass.
- Ngoại lệ: hết hạn, replay hoặc quá số lần thử làm transaction thất bại.
- Hậu điều kiện: session mới hoặc pre-auth transaction `FAILED`/`EXPIRED`.
- Yêu cầu đặc biệt: challenge gắn pre-auth transaction, IP/device context và TTL tối đa 5 phút.

### UC-03 — Xem và thu hồi phiên

- Actor: User. Tiền điều kiện: authenticated session.
- Luồng chính: xem session của chính mình, thu hồi session khả nghi.
- Ngoại lệ: cross-user access bị từ chối.
- Hậu điều kiện: session được đánh dấu revoked và token JTI không còn hợp lệ.
- Yêu cầu đặc biệt: không hiển thị hay lưu token raw.

### UC-04 — Xác nhận hoặc báo cáo login attempt

- Actor: User. Tiền điều kiện: user sở hữu attempt hoặc có one-time signed confirmation link.
- Luồng chính: xem ngữ cảnh tối thiểu, xác nhận hoặc báo cáo; hệ thống tạo audit event và thông báo SOC khi báo cáo.
- Ngoại lệ: link hết hạn/replay trả lỗi an toàn.
- Hậu điều kiện: feedback bất biến được lưu để tuyển chọn training data sau review.
- Yêu cầu đặc biệt: feedback không tự động đổi rule/model weight.

### UC-05 — Quản lý thiết bị tin cậy

- Actor: User. Tiền điều kiện: authenticated session.
- Luồng chính: xem, thêm hoặc bỏ device fingerprint hash của chính mình.
- Ngoại lệ: vượt giới hạn policy hoặc device đang bị block bị từ chối.
- Hậu điều kiện: thay đổi có audit event.
- Yêu cầu đặc biệt: trust giảm friction, không bypass lockout/MFA policy/hard block.

### UC-06 — Theo dõi SOC dashboard

- Actor: SOC Analyst. Tiền điều kiện: scope `alerts.read`.
- Luồng chính: xem tổng số attempt, alert, độ trễ event và ML degradation.
- Ngoại lệ: dữ liệu retention hết hạn hiển thị rõ phạm vi còn lại.
- Hậu điều kiện: không thay đổi dữ liệu.
- Yêu cầu đặc biệt: chỉ aggregate/raw context theo RBAC.

### UC-07 — Tìm kiếm login attempt

- Actor: SOC Analyst. Tiền điều kiện: scope `alerts.read`.
- Luồng chính: lọc theo thời gian, user, IP, outcome hoặc risk level; dùng cursor pagination.
- Ngoại lệ: truy vấn quá rộng bị giới hạn theo policy.
- Hậu điều kiện: không thay đổi dữ liệu.
- Yêu cầu đặc biệt: query sử dụng index thời gian và redaction phù hợp.

### UC-08 — Xem evidence rủi ro

- Actor: SOC Analyst. Tiền điều kiện: risk assessment tồn tại.
- Luồng chính: xem rule hit, version rule/policy/model, ML status, feature schema và audit timeline.
- Ngoại lệ: assessment `DEGRADED` hiển thị anomaly score là `null`, không là `0`.
- Hậu điều kiện: không thay đổi dữ liệu.
- Yêu cầu đặc biệt: reason code ML là heuristic, không tuyên bố causal explanation.

### UC-09 — Nhận và điều tra alert

- Actor: SOC Analyst. Tiền điều kiện: alert active.
- Luồng chính: `NEW → ACKNOWLEDGED → INVESTIGATING`, ghi note và audit event.
- Ngoại lệ: transition sai hoặc version stale trả `409`/`422`.
- Hậu điều kiện: trạng thái và owner của alert được cập nhật.
- Yêu cầu đặc biệt: optimistic lock bằng `If-Match`.

### UC-10 — Phân loại incident

- Actor: SOC Analyst. Tiền điều kiện: incident đang điều tra.
- Luồng chính: phân loại TRUE_POSITIVE, FALSE_POSITIVE hoặc NEEDS_WATCH với note.
- Ngoại lệ: incident closed không thể sửa nếu không có quy trình reopen được audit.
- Hậu điều kiện: classification và audit event được lưu.
- Yêu cầu đặc biệt: label chỉ vào training candidate queue sau review.

### UC-11 — Yêu cầu hành động bảo vệ

- Actor: SOC Analyst. Tiền điều kiện: evidence đầy đủ và quyền theo action policy.
- Luồng chính: tạo ActionRequest với evidence, expiry và idempotency key; core-app xác minh rồi `APPLIED`, `PENDING_APPROVAL` hoặc `REJECTED`.
- Ngoại lệ: forged/expired/duplicate request bị từ chối hoặc trả duplicate status.
- Hậu điều kiện: request và enforcement audit được liên kết.
- Yêu cầu đặc biệt: SOC không ghi trực tiếp user/session.

### UC-12 — Đóng incident

- Actor: SOC Analyst. Tiền điều kiện: classification, note và action resolution đáp ứng policy.
- Luồng chính: chuyển incident sang `RESOLVED`/`CLOSED`, giữ alert association và timeline.
- Ngoại lệ: trạng thái không hợp lệ hoặc concurrent edit bị từ chối.
- Hậu điều kiện: incident đóng có audit event.
- Yêu cầu đặc biệt: một incident có thể chứa nhiều alert; alert không tự tạo incident vô điều kiện.

### UC-13 — Quản lý tài khoản và role

- Actor: Security Admin. Tiền điều kiện: scope quản trị.
- Luồng chính: tạo/disable user, gán role theo least privilege.
- Ngoại lệ: không thể xóa hard-delete hoặc tự nâng quyền trái separation-of-duty.
- Hậu điều kiện: user/role version và audit được ghi.
- Yêu cầu đặc biệt: credential lifecycle không xuất password ra response/log.

### UC-14 — Quản lý version AuthPolicy

- Actor: Security Admin; Security Manager phê duyệt change high-impact.
- Luồng chính: tạo candidate, validate, approval, effective-at rồi active.
- Ngoại lệ: candidate không hợp lệ bị từ chối; rollback tạo version mới.
- Hậu điều kiện: active policy version mới; session cũ giữ semantics đã định nghĩa.
- Yêu cầu đặc biệt: immutable versions, two-person rule khi policy yêu cầu.

### UC-15 — Quản lý version RuleSet

- Actor: Security Admin; Security Manager phê duyệt khi policy yêu cầu.
- Luồng chính: propose, validate test vectors, approve và schedule RuleSet version.
- Ngoại lệ: threshold/weight không hợp lệ bị từ chối.
- Hậu điều kiện: assessment mới mang rule-set version đã dùng.
- Yêu cầu đặc biệt: rollback và canary/replay test trước activate.

### UC-16 — Cấu hình kênh thông báo

- Actor: Security Admin. Tiền điều kiện: secret reference có sẵn trong secret store.
- Luồng chính: cấu hình recipient, level, rate-limit; chạy test delivery rồi activate.
- Ngoại lệ: channel fail được đánh dấu `DEGRADED`, không retry vô hạn.
- Hậu điều kiện: versioned configuration và audit event.
- Yêu cầu đặc biệt: raw bot/API token không nằm DB config, log hay repo.

### UC-17 — Quản lý trust/block list

- Actor: Security Admin. Tiền điều kiện: lý do, creator và expiry được cung cấp.
- Luồng chính: tạo version TRUST/BLOCK cho IP/device/user đã normalize.
- Ngoại lệ: entry hết hạn không còn hiệu lực; duplicate active entry bị từ chối.
- Hậu điều kiện: rule assessment mới dùng list version tương ứng.
- Yêu cầu đặc biệt: BLOCK có thể nâng risk; TRUST không vượt hard security policy.

### UC-18 — Xem audit event

- Actor: Security Admin hoặc SOC có scope riêng.
- Luồng chính: lọc audit by actor/resource/correlation/time.
- Ngoại lệ: raw secret/credential fields luôn redacted.
- Hậu điều kiện: không thay đổi dữ liệu.
- Yêu cầu đặc biệt: audit append-only ở application role.

### UC-19 — Quản lý tham số vận hành

- Actor: Security Admin. Tiền điều kiện: giới hạn parameter được policy cho phép.
- Luồng chính: cập nhật candidate timeout, retention, threshold, notification rate; validate và schedule.
- Ngoại lệ: direct database update không là đường thao tác được hỗ trợ.
- Hậu điều kiện: immutable parameter version/audit event.
- Yêu cầu đặc biệt: mỗi deployment đọc configuration version rõ ràng.

### UC-20 — Xem dashboard quản lý

- Actor: Security Manager. Tiền điều kiện: read-only scope.
- Luồng chính: xem volume, risk distribution, alert/incident trend, lag và degraded rate.
- Ngoại lệ: dashboard hiển thị data freshness.
- Hậu điều kiện: không thay đổi dữ liệu.
- Yêu cầu đặc biệt: mặc định aggregate, không lộ PII không cần thiết.

### UC-21 — Xuất báo cáo aggregate

- Actor: Security Manager. Tiền điều kiện: report scope.
- Luồng chính: chọn range/template, tạo export server-side và download URL hết hạn.
- Ngoại lệ: range quá rộng được queue hoặc yêu cầu thu hẹp.
- Hậu điều kiện: report manifest/audit event được lưu.
- Yêu cầu đặc biệt: report redact PII và không chứa password, OTP hay token.

### UC-22 — Đánh giá Rule

- Actor: hệ thống, chạy bất đồng bộ sau outbox event.
- Luồng chính: deduplicate event, load active RuleSet version, tạo immutable RuleHit evidence.
- Ngoại lệ: rule execution failure tạo degraded assessment/audit, không drop event.
- Hậu điều kiện: rule score/version evidence sẵn sàng cho UC-24.
- Yêu cầu đặc biệt: idempotent theo event ID.

### UC-23 — Chấm điểm ML

- Actor: hệ thống, detection-engine gọi ml-service bằng workload identity.
- Luồng chính: gửi FeatureVector v1 theo thứ tự schema; ML xác thực workload identity, kiểm tra model `ACTIVE` đã được phê duyệt, schema/order, SHA-256 artifact và calibration; trả `inference_id`, score, model/artifact version và reason codes heuristic.
- Ngoại lệ: timeout 500 ms, breaker open, artifact không hợp lệ hoặc model không sẵn sàng trả `503 Problem`; detection-engine lưu `DEGRADED`, `anomaly_score=null`.
- Hậu điều kiện: score có danh tính truy vết hoặc degraded status sẵn sàng cho UC-24.
- Yêu cầu đặc biệt: ML không query database của detection-engine/core-app; evidence chỉ lưu digest feature vector, không copy raw IP/device/credential/OTP/token; reason codes không là giải thích nhân quả.

### UC-24 — Lưu risk assessment

- Actor: hệ thống.
- Luồng chính: tổng hợp rule score và optional ML score theo policy, lưu level/evidence/version.
- Ngoại lệ: missing ML signal giữ `ml_status=DEGRADED`; policy xác định rule-only behavior.
- Hậu điều kiện: risk assessment bất biến, có thể kích hoạt UC-25.
- Yêu cầu đặc biệt: lưu policy/rule/feature/model versions.

### UC-25 — Tạo alert

- Actor: hệ thống. Tiền điều kiện: risk assessment vượt alert threshold.
- Luồng chính: tạo tối đa một active alert trên login attempt, publish dashboard/notification work item.
- Ngoại lệ: duplicate delivery không tạo alert thứ hai.
- Hậu điều kiện: alert `NEW`; incident chỉ được associate theo policy/analyst.
- Yêu cầu đặc biệt: unique constraint, correlation ID và audit.

### UC-26 — Gửi thông báo

- Actor: hệ thống và Email/Telegram.
- Luồng chính: notification worker đọc work item, applies channel policy/rate limit, gửi idempotent.
- Ngoại lệ: bounded retry/backoff, dead-letter/degraded channel state.
- Hậu điều kiện: delivery status/audit được ghi, alert state không bị đổi bởi lỗi gửi.
- Yêu cầu đặc biệt: link signed, time-bound và không chứa credential/OTP/token.

## 3.1.3. Sơ đồ lớp và ERD

- Domain class diagram: [class.puml](class.puml).
- ERD theo database owner: [erd.puml](erd.puml).
- ML bounded-context class diagram: [ml-service-domain.puml](ml-service-domain.puml).
- ML internal ERD: [ml-service-erd.puml](ml-service-erd.puml).

Không có foreign key xuyên database. Projection/event references chỉ là contract references; consumer deduplicate bằng `event_id`.

Quy ước đọc sơ đồ:

- Đường liền là quan hệ có foreign key trong cùng database owner.
- `IncidentAlert` là association entity: `Incident 1—* IncidentAlert *—1 Alert`; nó lưu ai/thời điểm/lý do gom alert vào incident.
- `SocAuditEvent` sở hữu `AuditTargetReference`, một value object gồm `targetType + targetId`. Nó có thể tham chiếu Alert, Incident, ActionRequest, RuleSet hoặc TrustedList; nét đứt biểu thị logical reference, không phải foreign key.
- `TrustedListEntry` là policy input cho RiskAssessment, nên có nét đứt ảnh hưởng đánh giá thay vì quan hệ sở hữu dữ liệu.
- `ActionRequest → EnforcementAudit` nối detection-engine với core-app qua request ID/correlation ID; core-app vẫn là nơi duy nhất thay đổi User và Session.

## 3.1.4. Biểu đồ tuần tự

| ID | Nội dung | Source |
|---|---|---|
| ST-01 | Login synchronous + transactional outbox | [sequence-01-login.puml](sequence-01-login.puml) |
| ST-02 | MFA bằng pre-auth transaction | [sequence-02-mfa.puml](sequence-02-mfa.puml) |
| ST-03 | Detection async, alert, action enforcement | [sequence-03-alert.puml](sequence-03-alert.puml) |
| ST-04 | SOC investigation và action request | [sequence-04-soc-handle.puml](sequence-04-soc-handle.puml) |
| ST-05 | Rule change versioned/approved | [sequence-05-admin-rule.puml](sequence-05-admin-rule.puml) |
| ST-06 | ML timeout và degraded assessment | [sequence-06-ml-degraded.puml](sequence-06-ml-degraded.puml) |

ST-06 là error path bắt buộc: missing ML signal không được đổi thành score bằng `0` và không được ảnh hưởng quyết định synchronous authentication.
