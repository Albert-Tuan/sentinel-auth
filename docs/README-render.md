# Render PlantUML sang PNG

Script này dùng để render tất cả file `.puml` trong thư mục `docs/` sang PNG, lưu vào `docs/diagrams/`.

## Yêu cầu
- Java 8+ đã cài (`java -version` kiểm tra).
- File `plantuml.jar` (download 1 lần, dùng lại được).

## Bước 1 — Download PlantUML (chỉ làm 1 lần)
```bash
mkdir -p /tmp/plantuml
cd /tmp/plantuml
curl -fsSL -o plantuml.jar "https://github.com/plantuml/plantuml/releases/download/v1.2024.7/plantuml-1.2024.7.jar"
```

Kiểm tra:
```bash
java -jar /tmp/plantuml/plantuml.jar -version
```

## Bước 2 — Render tất cả file .puml
```bash
cd /home/thaus/GoogleDrive/Bài\ Tập/Information\ System/sentinel-auth/docs
java -Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8 \
     -jar /tmp/plantuml/plantuml.jar \
     -tpng -charset UTF-8 -o diagrams *.puml
```

**Giải thích flags**:
- `-Dfile.encoding=UTF-8 -Dsun.jnu.encoding=UTF-8`: JVM đọc file `.puml` dưới encoding UTF-8 (fix lỗi font khi file có tiếng Việt).
- `-charset UTF-8`: PlantUML xuất PNG dùng font hỗ trợ UTF-8.
- `-o diagrams`: thư mục output.
- `-tpng`: output định dạng PNG.

## Bước 3 — Verify
```bash
ls -la diagrams/
```

## File PlantUML trong repo

| File | Mô tả |
|------|-------|
| `use-case.puml` | Sơ đồ Use-case tổng quát (26 UC) |
| `class.puml` | Sơ đồ lớp (3 package) |
| `sequence-01-login.puml` | ST-01: Đăng nhập happy path |
| `sequence-02-mfa.puml` | ST-02: Đăng nhập có MFA |
| `sequence-03-alert.puml` | ST-03: Login CRITICAL → tạo Alert |
| `sequence-04-soc-handle.puml` | ST-04: SOC xử lý Alert đến khi đóng Incident |
| `sequence-05-admin-rule.puml` | ST-05: Admin cấu hình Rule |

## Render 1 file riêng lẻ
```bash
java -Dfile.encoding=UTF-8 -jar /tmp/plantuml/plantuml.jar -tpng -charset UTF-8 use-case.puml
```

## Lỗi thường gặp

### "File encoding error" / font bị ô vuông
- Nguyên nhân: thiếu JVM `-Dfile.encoding=UTF-8`.
- Fix: dùng command ở Bước 2 có đủ flags.

### PlantUML không nhận diện cú pháp
- Mở file `.puml` bằng editor (VS Code), xem có highlight đúng không.
- Thử đổi tên `@startuml use-case-tong-quat` thành `@startuml` (không có alias).

### PNG bị trắng / trống
- Kiểm tra file `.puml` có `@startuml` ở đầu và `@enduml` ở cuối.