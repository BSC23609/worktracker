"""Create tables and seed the employee roster. Idempotent.

Run once after setting DATABASE_URL (locally or against Neon):
    DATABASE_URL="postgresql+psycopg2://..." python scripts/init_db.py

Existing users are left untouched (matched by email or emp code), so re-running
never resets anyone's password. New users get the default password and must
reset it on first login. Everyone can sign in with their email OR employee code.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, or_, select  # noqa: E402

from app import config  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import ROLE_SUPERADMIN, ROLE_USER, User  # noqa: E402

# (emp_code, name, email, whatsapp, role). email may be "" (login by emp code).
SEED_USERS = [
    ("BSC/003", "MURKESH M.P.R", "purchase@bharatsteels.in", "919444085020", "user"),
    ("BSC/004", "NALLASIVAM D", "", "919444085018", "user"),
    ("BSC/005", "PARAMAGURU S", "", "919444085015", "user"),
    ("BSC/006", "BAKTHAVACHALAM C", "baktha@bharatsteels.in", "919444085016", "user"),
    ("BSC/012", "VENKATESH PRASAD DOBA", "", "917200006787", "user"),
    ("BSC/017", "SHIVAM SHROFF", "", "919884384261", "user"),
    ("BSC/074", "SUSMITHA AVULA", "connect@bharatsteels.in", "916281867026", "user"),
    ("BSC/098", "KANNAN K", "kannan@bharatsteels.in", "919840299625", "user"),
    ("BSC/119", "JEEVABHARATHY S", "jeeva@bharatsteels.in", "917395956648", "superadmin"),
    ("BSC/136", "NAGASUBRAMANIAN N", "sap@bharatsteels.in", "919894174741", "user"),
    ("BSC/160", "RAJASEKAR", "hr@bharatsteels.in", "918825849418", "user"),
    ("CEO", "GOURAV SARAF", "gourav@bharatsteels.in", "919884696666", "superadmin"),
    ("CMD", "GOVERDHAN AGARWAL", "cmd@bharatsteels.in", "919444088086", "superadmin"),
    ("G2S/058", "GANAPATHY P", "ganapathy@bharatsteels.in", "919840630463", "user"),
    ("TECH", "MOHAN", "inspace_it@bharatsteels.in", "919384819376", "user"),
    ("MET106", "BALAJI M", "accounts@metfraa.com", "918637466998", "user"),
    ("MET66", "BODAPATI SHEELA HEPSIBAH GRACE", "admin@metfraa.com", "919963315234", "user"),
    ("MET110", "KALAI BRINDHA M P", "vp@metfraa.com", "919600068189", "user"),
    ("MET51", "KHAJA SHERIFF", "khajasheriff.m@metfraa.com", "917010507589", "user"),
    ("MET78", "NIRMAL KUMAR BALAKRISHNAN", "nirmal@metfraa.com", "919840485801", "user"),
    ("MET64", "P. THANGARAJ", "thangaraj@metfraa.com", "919994086097", "user"),
    ("MET92", "VARATHARAJ NAVANEETHAN", "varadharaj@metfraa.com", "919790249180", "user"),
    ("MET-MD", "VELARASU", "arasu@metfraa.com", "919787720731", "superadmin"),
]


def main():
    init_db()
    db = SessionLocal()
    created = 0
    for emp_code, name, email, whatsapp, role in SEED_USERS:
        emp_code = emp_code.strip().upper()
        email = email.strip().lower()
        existing = db.scalar(select(User).where(or_(
            func.upper(User.emp_code) == emp_code,
            func.lower(User.email) == email if email else False,
        )))
        if existing:
            if not existing.emp_code:          # backfill emp code onto an older row
                existing.emp_code = emp_code
            continue
        db.add(User(
            emp_code=emp_code or None, name=name.strip(), email=email or None,
            whatsapp=whatsapp.strip() or None,
            role=ROLE_SUPERADMIN if role == "superadmin" else ROLE_USER,
            password_hash=hash_password(config.DEFAULT_PASSWORD),
            must_reset=True, active=True))
        created += 1
    db.commit()
    total = db.scalar(select(func.count()).select_from(User))
    print(f"Schema ready. Users created this run: {created}. Total users now: {total}.")
    print(f"Default password: {config.DEFAULT_PASSWORD} (each user must change it on first login).")
    db.close()


if __name__ == "__main__":
    main()
