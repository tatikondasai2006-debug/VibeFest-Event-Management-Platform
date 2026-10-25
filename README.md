# VibeFest 2026 — Event Management & Ticketing Platform

A full-stack Flask web application for music festival and concert management, featuring lineup showcases, member authentication, tier-based ticket reservations, administrative controls, and multimedia integration.

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=for-the-badge&logo=python)
![Flask](https://img.shields.io/badge/Flask-Web_Framework-black?style=for-the-badge&logo=flask)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-Database-red?style=for-the-badge)
![Security](https://img.shields.io/badge/Security-CSRF_%26_Rate_Limiting-green?style=for-the-badge)

---

## 🎪 Key Highlights

- **Interactive Festival Experience:** Video clip previews, artist lineup explorer, schedule timeline, and stage breakdown.
- **Member Authentication & Profiles:** Dual-session architecture resolving both administrative users and festival attendees/members.
- **Ticket Booking & Pass Tiering:** General Admission, VIP, and Backstage pass reservation flows with inventory safeguards.
- **Admin Command Center:** Real-time metrics on registrations, ticket sales distribution, capacity monitoring, and demo seeder.
- **Production-Ready Security:** Rate-limiting via Flask-Limiter, CSRF token validation on all mutating endpoints, and secure password hashing.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10+
- Virtualenv

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/tatikondasai2006-debug/VibeFest-Event-Management-Platform.git
cd VibeFest-Event-Management-Platform

# Create virtual environment & activate
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Setup environment variables
cp .env.example .env
```

### 3. Database Initialization & Demo Data

```bash
# Apply migrations
flask db upgrade

# Run development server
python run.py
```

Open `http://localhost:5000` to explore the festival portal.

---

## 🧪 Automated Testing

```bash
# Run pytest test suite
pytest
```

---

## 📄 License

This project is licensed under the MIT License.
