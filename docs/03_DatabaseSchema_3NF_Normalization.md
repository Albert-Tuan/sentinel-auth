# Database Schema v4 - 3NF Normalization

> Chuẩn hóa database schema từ v3.1 sang v4 theo Third Normal Form (3NF)

---

## Tổng quan thay đổi

| Metric | v3.1 | v4 (3NF) | Change |
|--------|-------|-----------|--------|
| Tables | 19 | 37 | +18 |
| Columns | 182 | ~200 | +18 |
| Foreign Keys | 20 | ~45 | +25 |
| Indexes | 50 | ~65 | +15 |

---

## 3NF Rules Applied

### 1NF: Atomic Values (Đã thỏa mãn trong v3.1)
- ✅ Không có repeating groups
- ✅ Mỗi column chỉ chứa single value
- ✅ Atomic primary keys

### 2NF: No Partial Dependencies (Cải thiện)
- ✅ Tất cả non-key columns phụ thuộc hoàn toàn vào primary key
- ✅ Không có composite keys có partial dependency

### 3NF: No Transitive Dependencies (MỚI)
- ❌ **Vấn đề cũ:** `assigned_to` (TEXT) trong `alerts` → phụ thuộc transitive vào `users`
- ❌ **Vấn đề cũ:** `actor` (TEXT) trong `alert_timeline` → phụ thuộc transitive vào `users`
- ❌ **Vấn đề cũ:** `resolved_by` (TEXT) trong `alerts` → phụ thuộc transitive vào `users`
- ❌ **Vấn đề cũ:** `status` (TEXT) trong nhiều bảng → không có reference table

---

## Tables mới được tạo

### Reference Tables (18 bảng)

| Table | Mô tả | Giá trị |
|-------|--------|---------|
| `ref_user_status` | User status lookup | active, suspended, locked |
| `ref_roles` | Role definitions | USER, SECURITY_ADMIN, SOC_ANALYST, SECURITY_MANAGER |
| `ref_mfa_type` | MFA types | one_time, persistent |
| `ref_mfa_transaction_status` | MFA transaction statuses | pending, completed, expired, failed |
| `ref_mfa_channel` | MFA channels | email, sms, totp |
| `ref_login_outcome` | Login outcomes | 8 values |
| `ref_risk_level` | Risk levels | low, medium, high, critical |
| `ref_detection_decision` | Detection decisions | allow, challenge, block |
| `ref_alert_status` | Alert statuses | open, acknowledged, resolved, false_positive |
| `ref_alert_event_type` | Timeline event types | 8 values |
| `ref_detection_stage` | Detection stages | rule, ml, combined, action |
| `ref_ml_status` | ML inference statuses | success, unavailable, error |
| `ref_notification_type` | Notification types | 8 values |
| `ref_notification_priority` | Priority levels | low, normal, high, urgent |
| `ref_settings_category` | Settings categories | 6 values |
| `ref_settings_value_type` | Settings value types | string, integer, boolean, json |
| `ref_outbox_status` | Outbox event statuses | pending, processing, published, failed |

### Core Tables mới (2 bảng)

| Table | Mô tả | Lý do |
|-------|--------|--------|
| `ip_addresses` | Normalized IP tracking | Loại bỏ duplicate IP data, thêm geolocation |
| `soc_analysts` | SOC analyst profiles | Normalize `assigned_to`, `resolved_by` |

---

## Normalization Examples

### Trước (v3.1 - Vi phạm 3NF)

```sql
-- alerts table có transitive dependency
alerts {
    assigned_to TEXT,  -- phụ thuộc transitive: 
                      -- assigned_to → users.username → users.id
    resolved_by TEXT,  -- phụ thuộc transitive tương tự
}
```

### Sau (v4 - 3NF Compliant)

```sql
-- soc_analysts table break transitive dependency
soc_analysts {
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),  -- Direct reference
    display_name TEXT,
    is_active BOOLEAN,
    max_alerts INTEGER
}

-- alerts table references analyst, not username
alerts {
    assigned_to_id UUID REFERENCES soc_analysts(id),  -- Direct FK
    resolved_by_id UUID REFERENCES soc_analysts(id),  -- Direct FK
}
```

---

## Cấu trúc thư mục Migration

```
infra/postgres/
├── schema-v3.1.sql                    # Schema cũ
├── schema-v4-3nf.sql                 # Schema mới (3NF)
└── migrations/
    └── 004_normalize_to_3nf.sql      # Migration script
```

---

## Migration Steps

### Step 1: Backup
```bash
pg_dump -Fc sentinel_auth > backup_v3.1_$(date +%Y%m%d).dump
```

### Step 2: Run migration
```bash
psql -d sentinel_auth -f migrations/004_normalize_to_3nf.sql
```

### Step 3: Verify
```sql
-- Check FK constraints
SELECT * FROM information_schema.table_constraints 
WHERE constraint_type = 'FOREIGN KEY' 
AND table_schema = 'public';

-- Check reference tables populated
SELECT COUNT(*) FROM ref_roles;
SELECT COUNT(*) FROM ref_user_status;
```

### Step 4: Update application code
- Update all enum usages to use FK references
- Add lookup queries for reference tables

---

## Query Pattern Changes

### Before (v3.1)
```python
# Using TEXT values directly
alert.status = 'open'
alert.assigned_to = 'soc_analyst_1'
```

### After (v4)
```python
# Using FK references
alert.status_id = status_lookup['open'].id
alert.assigned_to_id = analyst.id

# With proper joins
SELECT a.*, rs.name as status_name, sa.display_name as analyst_name
FROM alerts a
JOIN ref_alert_status rs ON a.status_id = rs.id
JOIN soc_analysts sa ON a.assigned_to_id = sa.id
```

---

## Benefits of 3NF Normalization

### Data Integrity
- ✅ FK constraints ensure referential integrity
- ✅ Không thể có orphaned records
- ✅ CASCADE deletes work properly

### Maintainability
- ✅ Thay đổi enum value chỉ cần update 1 row
- ✅ Thêm enum value mới không cần ALTER TABLE
- ✅ Centralized reference data

### Query Performance
- ✅ Indexes on all FKs
- ✅ Proper composite indexes for common queries
- ✅ Partial indexes for filtered queries

### Documentation
- ✅ Self-documenting schema
- ✅ Reference tables act as data dictionary
- ✅ Descriptions in comments

---

## Potential Issues & Solutions

### Issue: Too many JOINs
**Solution:** Use database views for common queries

```sql
CREATE VIEW v_alerts_full AS
SELECT 
    a.*,
    la.occurred_at,
    la.source_ip,
    rs.name AS status_name,
    rl.name AS risk_level_name,
    sa.display_name AS analyst_name,
    u.username AS assigned_username
FROM alerts a
JOIN login_attempts la ON a.login_attempt_id = la.id
JOIN ref_alert_status rs ON a.status_id = rs.id
JOIN ref_risk_level rl ON a.risk_level_id = rl.id
LEFT JOIN soc_analysts sa ON a.assigned_to_id = sa.id
LEFT JOIN users u ON sa.user_id = u.id;
```

### Issue: Query complexity
**Solution:** Use ORM with proper relationships

```python
class Alert(Base):
    __tablename__ = 'alerts'
    
    status = relationship('RefAlertStatus', backref='alerts')
    risk_level = relationship('RefRiskLevel', backref='alerts')
    assigned_analyst = relationship('SocAnalyst', backref='assigned_alerts')
```

---

## Rollback Plan

⚠️ **Migration này không reversible tự động**

Để rollback:
1. Restore từ backup: `pg_restore -d sentinel_auth backup_v3.1_*.dump`
2. Hoặc viết migration script riêng để đảo ngược

---

## Checklist trước khi deploy

- [ ] Backup database hoàn chỉnh
- [ ] Test migration trên staging
- [ ] Update application code để sử dụng FK references
- [ ] Update any raw SQL queries
- [ ] Update API documentation
- [ ] Train team on new query patterns
- [ ] Monitor for query performance issues
- [ ] Create database views cho common queries
