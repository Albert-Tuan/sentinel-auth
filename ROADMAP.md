# Roadmap — sentinel-auth

> Tài liệu này là **LỚP 3** trong bộ 3 lớp plan. Chia theo tuần và milestone. Có thể điều chỉnh nếu nhóm nhanh/chậm hơn dự kiến.

## Tổng quan 4 tuần

```
Tuần 1          Tuần 2          Tuần 3          Tuần 4
Spec + skeleton  Core flow       SOC dashboard   Polish + báo cáo
```

| Tuần | Milestone | Người chịu trách nhiệm chính |
|------|-----------|-------------------------------|
| 1 | Spec + Docker skeleton | Cursor + 3 người |
| 2 | End-to-end core flow | Sony + Tuấn Anh + Khang |
| 3 | SOC dashboard + attack demo | Tuấn Anh + Sony |
| 4 | Polish + báo cáo | Cả nhóm + Cursor |

---

## Tuần 1 — Spec & Skeleton (ngày 1-7)

**Mục tiêu**: Hệ thống chạy được trên docker-compose, mỗi service có healthcheck pass.

### Ngày 1-2: INFRA tickets
- **TICKET-INFRA-01** (docker skeleton) ← bắt đầu ngay
- **TICKET-INFRA-02** (OpenAPI spec)
- **TICKET-INFRA-05** (Alembic migration)
- **TICKET-DOCS-01** (render PlantUML sang PNG)
- Người: Cursor (tôi) + 3 người review contract.

### Ngày 3-5: Core skeletons
- Sony: **TICKET-CORE-AUTH-01** (user model + password hash) + skeleton login route.
- Tuấn Anh: **TICKET-DET-RULE-01** (rule model + seed) + skeleton event receiver.
- Khang: **TICKET-ML-DATA-01** (synthetic data generator) + skeleton feature module.
- Cả 3 người commit vào branch riêng của mình, mỗi ngày standup 15 phút.

### Ngày 6-7: Integration test đầu tiên
- 3 service chạy được trong docker-compose.
- Healthcheck pass cả 3.
- Có thể curl `/health` của từng service.
- **Milestone check**: chưa cần flow nghiệp vụ hoàn chỉnh, chỉ cần hệ thống "sống".

### Checkpoint cuối tuần 1
- [ ] `docker-compose up` thành công.
- [ ] 3 service có Swagger UI.
- [ ] Alembic migration tạo đủ tables.
- [ ] Tất cả PNG diagrams đã render.
- [ ] OpenAPI spec đã review xong bởi 3 người.

---

## Tuần 2 — Core Flow (ngày 8-14)

**Mục tiêu**: User login → core-app tạo session → detection-engine nhận event → gọi ml-service → trả risk score → tạo alert nếu HIGH/CRITICAL.

### Ngày 8-10: Sony (core-app)
- **TICKET-CORE-AUTH-02** (login endpoint) — *blocker của nhiều ticket khác*
- **TICKET-CORE-AUTH-03** (MFA)
- **TICKET-CORE-AUTH-04** (RBAC)
- **TICKET-CORE-INTEG-01** (push login event to detection-engine)

### Ngày 8-10: Tuấn Anh (detection-engine) — song song với Sony
- **TICKET-DET-RULE-02** (rule evaluation engine — 6 rule)
- **TICKET-DET-INTEG-01** (receive login event)
- **TICKET-DET-INTEG-02** (call ml-service)

### Ngày 8-10: Khang (ml-service) — song song
- **TICKET-ML-FEAT-01** (feature pipeline)
- **TICKET-ML-MODEL-01** (train Isolation Forest)
- **TICKET-ML-API-01** (inference API)
- **TICKET-ML-MODEL-02** (model versioning)
- **TICKET-ML-OPS-01** (healthcheck)

### Ngày 11-12: Tích hợp & sửa lỗi
- 3 người cùng test integration.
- Sửa các lỗi schema mismatch, payload sai.
- **TICKET-INFRA-04** (end-to-end smoke test) — viết bởi ai rảnh nhất.

### Ngày 13-14: Risk engine & alert
- Tuấn Anh: **TICKET-DET-RISK-01** (risk aggregation) + **TICKET-DET-ALERT-01** (alert creation)
- Tuấn Anh: **TICKET-DET-INTEG-03** (push action to core-app)
- Sony: **TICKET-CORE-INTEG-02** (receive action from detection-engine)

### Checkpoint cuối tuần 2
- [ ] User login thật → có session.
- [ ] Login event được push đến detection-engine.
- [ ] Detection chạy 6 rule + gọi ML → trả risk score.
- [ ] Alert được tạo khi risk = HIGH.
- [ ] ML trả đúng score với data test.
- [ ] Smoke test pass.

---

## Tuần 3 — SOC Dashboard & Attack Demo (ngày 15-21)

**Mục tiêu**: SOC Analyst có dashboard thật để xử lý alert; có script demo tấn công để trình bày.

### Ngày 15-17: Tuấn Anh (SOC Dashboard)
- **TICKET-DET-API-01** (SOC Dashboard API — alerts list, detail, status update)
- **TICKET-DET-AUDIT-01** (audit log cho mọi thay đổi)
- Tạo template HTML đơn giản cho dashboard (hoặc đợi frontend).

### Ngày 15-17: Sony (User mgmt + Attack scripts)
- **TICKET-CORE-USER-01** (user management API cho admin)
- **TICKET-CORE-USER-02** (session & trusted device management)
- **TICKET-CORE-ATK-01** (attack scripts cho demo)

### Ngày 15-17: Khang (Polish ML)
- Viết test cases bổ sung.
- Log model metrics ra dashboard.
- (Optional) thử nghiệm với dataset lớn hơn.

### Ngày 18-19: Frontend (nếu chốn có frontend)
- Nếu **Streamlit**: 1 ngày là xong.
- Nếu **Next.js/React**: cần 3-4 ngày, chuyển sang tuần 4.

### Ngày 20-21: Demo flow
- Chạy attack script → verify alert xuất hiện → SOC xử lý → đóng incident.
- Quay video demo 5 phút (optional).

### Checkpoint cuối tuần 3
- [ ] SOC login → xem dashboard → xử lý alert → đóng incident.
- [ ] Audit log ghi nhận mọi thao tác.
- [ ] Admin quản lý user, khóa/mở khóa.
- [ ] Attack scripts chạy được và trigger alert tương ứng.

---

## Tuần 4 — Polish & Báo cáo (ngày 22-28)

**Mục tiêu**: Báo cáo Word mục 3.1 hoàn chỉnh + cả hệ thống chạy mượt.

### Ngày 22-23: TICKET-DOCS-02 (Báo cáo Word)
- Cursor viết nội dung 3.1 vào file Word.
- Mỗi người review phần của mình.
- TICKET-DOCS-03 (README từng service).

### Ngày 24-25: Polish
- Test toàn hệ thống với data lớn hơn (10k → 100k events).
- Sửa UI/UX bugs.
- Thêm error handling, logging.
- (Optional) thêm frontend nếu chưa có.

### Ngày 26-27: Test cuối & bug fixes
- Chạy tất cả test (unit + e2e).
- Đảm bảo test coverage ≥ 60%.
- Sửa bug phát sinh.

### Ngày 28: Đóng gói & nộp
- Final commit.
- Viết release notes.
- Nộp báo cáo.

### Checkpoint cuối tuần 4
- [ ] Báo cáo Word mục 3.1 đầy đủ 4 thành phần + diagrams PNG.
- [ ] Tất cả test pass.
- [ ] `docker-compose up` chạy mượt, không cần fix gì.
- [ ] README đầy đủ.

---

## Risk register & mitigation

| Rủi ro | Xác suất | Tác động | Mitigation |
|--------|----------|----------|------------|
| OpenAPI contract thay đổi giữa chừng | Trung bình | Cao | Sync mỗi 2 ngày, breaking change phải báo trước 1 ngày. |
| ML accuracy thấp (F1 < 0.6) | Thấp | Trung bình | Dùng synthetic data dễ predict; nếu fail, giảm contamination hoặc thử OneClassSVM. |
| TimescaleDB extension không cài được trên máy thành viên | Thấp | Trung bình | Fallback: dùng Postgres plain + index trên `timestamp`. |
| Một thành viên chậm tiến độ | Trung bình | Cao | Mỗi ticket độc lập, người khác có thể pick up. INFRA tickets do tôi lo. |
| Khang chưa rành ML | Thấp | Thấp | Có script generate data + template train, chỉ cần chạy theo. |
| Frontend không kịp | Cao | Trung bình | Fallback: dùng Swagger UI + HTML template đơn giản, bỏ frontend riêng. |

---

## Daily standup template

Mỗi ngày, mỗi thành viên update 1 dòng vào `DAILY.md`:

```markdown
## Ngày X - Tên
- Đã làm: TICKET-XYZ-01 (xong), TICKET-XYZ-02 (50%)
- Sẽ làm: TICKET-XYZ-02 (tiếp)
- Blocked: chờ OpenAPI spec update (cần @tên-người)
```

---

## Definition of Done cho toàn dự án

- [ ] Tất cả ticket trong TICKETS.md có status DONE.
- [ ] Test coverage mỗi service ≥ 60%.
- [ ] `docker-compose up` chạy thành công, tất cả healthcheck pass.
- [ ] Demo flow: login → risk score → alert → SOC xử lý → đóng incident hoạt động end-to-end.
- [ ] Báo cáo Word mục 3.1 đầy đủ 4 thành phần (Use-case diagram + 12 UC đặc tả + Class diagram + 5 Sequence diagram) với PNG.
- [ ] README từng service đầy đủ (kiến trúc, cách chạy, API, env vars).
- [ ] Không còn bug critical nào trong GH issues (nếu dùng).

---

**Bạn đã có đủ 3 lớp plan**: PLAN.md + TICKETS.md + ROADMAP.md. Bước tiếp theo là bắt đầu tuần 1 — INFRA tickets, sau đó mỗi người pick ticket của mình theo roadmap.