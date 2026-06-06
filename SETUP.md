# LancersPulse — Setup Instructions

## First time setup

```bash
# 1. Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt
pip install Pillow

# 3. Run migrations
python manage.py migrate

# 4. Load demo data (creates all teams, players, injuries)
python manage.py load_demo_data

# 5. Start server
python manage.py runserver
```

## Demo login credentials

| Role | Username | Password |
|------|----------|----------|
| Admin / Director (Chad) | chad | chad1234 |
| Athletic Therapist | therapist1 | demo1234 |
| Coach (Men's Hockey) | coach_hockeym | demo1234 |
| Coach (Women's Soccer) | coach_soccerw | demo1234 |
| Coach (Football) | coach_football | demo1234 |
| Player | player_mh1 | demo1234 |

## Demo highlights
- Men's Hockey: 8 shoulder injuries (80% of team injuries) — Chad's exact example
- Women's Soccer: 17 missed games 2025 vs 34 in 2024 — year-over-year comparison
- 5 teams, 44 players, 40+ injuries across 2024 and 2025 seasons
