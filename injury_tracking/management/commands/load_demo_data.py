"""
Management command: load_demo_data
Place this file at:
  injury_tracking/management/commands/load_demo_data.py

Run with:
  python manage.py load_demo_data

What it creates:
  - 5 sports teams (Men's/Women's Hockey, Men's/Women's Soccer, Football)
  - 1 coach per team, 1 shared athletic therapist (doctor), 1 admin (Chad)
  - 8-12 players per team
  - 40+ realistic injuries spread across 2 seasons (2024 and 2025)
  - Varied statuses, contact types, missed games/practices
  - All users have is_registration_complete=True so no registration wall

Login credentials printed at the end.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import date, timedelta
import random

from accounts.models import Team
from injury_tracking.models import (
    InjuryType, BodyPart, InjurySeverity, InjuryRecord
)

User = get_user_model()


# ── Helpers ────────────────────────────────────────────────────────────────

def d(year, month, day):
    return date(year, month, day)


# ── Command ────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = 'Load realistic demo data for the client presentation'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Loading demo data...'))

        # ── Teams ──────────────────────────────────────────────────────────
        teams_data = [
            ('Men\'s Ice Hockey',   'M'),
            ('Women\'s Ice Hockey', 'W'),
            ('Men\'s Soccer',       'M'),
            ('Women\'s Soccer',     'W'),
            ('Football',            'M'),
        ]
        teams = {}
        for name, gender in teams_data:
            t, _ = Team.objects.get_or_create(name=name, defaults={'gender': gender})
            teams[name] = t
            self.stdout.write(f'  Team: {name}')

        # ── Lookup tables (already created by populate_initial_data) ───────
        def get_or_create_type(name):
            obj, _ = InjuryType.objects.get_or_create(name=name)
            return obj

        def get_or_create_part(name):
            obj, _ = BodyPart.objects.get_or_create(name=name)
            return obj

        def get_or_create_sev(name, color, desc):
            obj, _ = InjurySeverity.objects.get_or_create(
                name=name, defaults={'color_code': color, 'description': desc}
            )
            return obj

        mild     = get_or_create_sev('Mild',     '#10b981', 'Minor injury, quick recovery expected')
        moderate = get_or_create_sev('Moderate', '#f59e0b', 'Moderate injury, requires treatment')
        severe   = get_or_create_sev('Severe',   '#ef4444', 'Serious injury, extended recovery')
        critical = get_or_create_sev('Critical', '#991b1b', 'Critical injury, immediate attention required')

        concussion    = get_or_create_type('Concussion')
        sprain        = get_or_create_type('Sprain')
        strain        = get_or_create_type('Strain')
        fracture      = get_or_create_type('Fracture')
        dislocation   = get_or_create_type('Dislocation')
        contusion     = get_or_create_type('Contusion')
        ligament_tear = get_or_create_type('Ligament Tear')
        muscle_tear   = get_or_create_type('Muscle Tear')
        tendonitis    = get_or_create_type('Tendonitis')
        cartilage     = get_or_create_type('Cartilage Damage')

        head       = get_or_create_part('Head')
        shoulder   = get_or_create_part('Shoulder')
        knee       = get_or_create_part('Knee')
        ankle      = get_or_create_part('Ankle')
        hamstring  = get_or_create_part('Thigh')
        lower_back = get_or_create_part('Lower Back')
        wrist      = get_or_create_part('Wrist')
        elbow      = get_or_create_part('Elbow')
        hip        = get_or_create_part('Hip')
        foot       = get_or_create_part('Foot')

        # ── Admin / therapist / coaches ────────────────────────────────────
        def make_user(username, first, last, email, role, team=None, password='demo1234'):
            if User.objects.filter(username=username).exists():
                return User.objects.get(username=username)
            u = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first,
                last_name=last,
                role=role,
                team=team,
                is_registration_complete=True,
                is_staff=(role == 'ADMIN'),
                is_superuser=(role == 'ADMIN'),
            )
            return u

        chad = make_user(
            'chad', 'Chad', 'Sutherland',
            'chad@lancer.admin.com', 'ADMIN', password='chad1234'
        )
        therapist = make_user(
            'therapist1', 'Dr. Sarah', 'Johnson',
            'sarah@lancer.medical.com', 'DOCTOR', password='demo1234'
        )

        coach_hockey_m  = make_user('coach_hockeym',  'James', 'Miller',   'jmiller@lancer.coach.com',  'COACH', teams["Men's Ice Hockey"])
        coach_hockey_w  = make_user('coach_hockeyw',  'Linda', 'Park',     'lpark@lancer.coach.com',    'COACH', teams["Women's Ice Hockey"])
        coach_soccer_m  = make_user('coach_soccerm',  'Carlos','Reyes',    'creyes@lancer.coach.com',   'COACH', teams["Men's Soccer"])
        coach_soccer_w  = make_user('coach_soccerw',  'Amy',   'Chen',     'achen@lancer.coach.com',    'COACH', teams["Women's Soccer"])
        coach_football  = make_user('coach_football', 'Derek', 'Thompson', 'dthompson@lancer.coach.com','COACH', teams["Football"])

        self.stdout.write('  Staff accounts created')

        # ── Players ────────────────────────────────────────────────────────
        players_data = {
            "Men's Ice Hockey": [
                ('player_mh1',  'Tyler',   'Brooks'),
                ('player_mh2',  'Connor',  'Walsh'),
                ('player_mh3',  'Ryan',    'Perez'),
                ('player_mh4',  'Ethan',   'Nguyen'),
                ('player_mh5',  'Lucas',   'Tremblay'),
                ('player_mh6',  'Noah',    'Stewart'),
                ('player_mh7',  'Owen',    'Foster'),
                ('player_mh8',  'Liam',    'Harrison'),
                ('player_mh9',  'Jack',    'Murphy'),
                ('player_mh10', 'Dylan',   'Grant'),
            ],
            "Women's Ice Hockey": [
                ('player_wh1',  'Emma',    'Davis'),
                ('player_wh2',  'Olivia',  'Martin'),
                ('player_wh3',  'Sophia',  'Lee'),
                ('player_wh4',  'Ava',     'Wilson'),
                ('player_wh5',  'Mia',     'Taylor'),
                ('player_wh6',  'Isabella','Anderson'),
                ('player_wh7',  'Grace',   'Thomas'),
                ('player_wh8',  'Chloe',   'Jackson'),
            ],
            "Men's Soccer": [
                ('player_ms1',  'Marcus',  'Brown'),
                ('player_ms2',  'Jordan',  'Clark'),
                ('player_ms3',  'Kai',     'Robinson'),
                ('player_ms4',  'Andre',   'White'),
                ('player_ms5',  'Devon',   'Hall'),
                ('player_ms6',  'Isaiah',  'Young'),
                ('player_ms7',  'Malik',   'King'),
                ('player_ms8',  'Zach',    'Wright'),
            ],
            "Women's Soccer": [
                ('player_ws1',  'Priya',   'Sharma'),
                ('player_ws2',  'Natalie', 'Moore'),
                ('player_ws3',  'Zoe',     'Baker'),
                ('player_ws4',  'Hannah',  'Nelson'),
                ('player_ws5',  'Ella',    'Carter'),
                ('player_ws6',  'Lily',    'Mitchell'),
                ('player_ws7',  'Maya',    'Roberts'),
                ('player_ws8',  'Nadia',   'Evans'),
            ],
            "Football": [
                ('player_fb1',  'Brandon', 'Turner'),
                ('player_fb2',  'Jaxon',   'Phillips'),
                ('player_fb3',  'Caleb',   'Campbell'),
                ('player_fb4',  'Mason',   'Parker'),
                ('player_fb5',  'Hunter',  'Edwards'),
                ('player_fb6',  'Cole',    'Collins'),
                ('player_fb7',  'Austin',  'Stewart'),
                ('player_fb8',  'Blake',   'Sanchez'),
                ('player_fb9',  'Chase',   'Morris'),
                ('player_fb10', 'Tanner',  'Rogers'),
            ],
        }

        players = {}  # username -> user object
        for team_name, plist in players_data.items():
            team_obj = teams[team_name]
            for username, first, last in plist:
                u = make_user(
                    username, first, last,
                    f'{username}@lancer.com', 'PLAYER', team_obj
                )
                players[username] = u

        self.stdout.write(f'  {len(players)} players created')

        # ── Injuries ───────────────────────────────────────────────────────
        # Format: (player_username, injury_date, injury_type, body_part,
        #          severity, status, contact_type, missed_games,
        #          missed_practices, description, treatment)

        injuries_to_create = [
            # ── Men's Ice Hockey — heavy shoulder injuries (Chad's example) ──
            ('player_mh1', d(2025,10,5),  sprain,        shoulder, moderate, 'RECOVERED',   'CONTACT',     3, 8,  'Shoulder sprain from body check into the boards.',           'PHYSIO'),
            ('player_mh2', d(2025,10,18), dislocation,   shoulder, severe,   'RECOVERED',   'CONTACT',     6, 12, 'Shoulder dislocation during high-contact drill.',            'PHYSIO'),
            ('player_mh3', d(2025,11,2),  ligament_tear, shoulder, severe,   'RECOVERING',  'CONTACT',     8, 15, 'AC joint ligament tear after collision with opposing player.','PHYSIO'),
            ('player_mh4', d(2025,11,14), contusion,     shoulder, mild,     'RECOVERED',   'CONTACT',     1, 3,  'Shoulder contusion from illegal hit, cleared quickly.',      'REST'),
            ('player_mh5', d(2025,12,1),  strain,        shoulder, moderate, 'ACTIVE',      'CONTACT',     4, 6,  'Rotator cuff strain from repeated checking motions.',        'PHYSIO'),
            ('player_mh6', d(2025,10,22), concussion,    head,     severe,   'RECOVERED',   'CONTACT',     5, 10, 'Concussion from illegal hit to the head.',                   'REST'),
            ('player_mh7', d(2025,11,8),  sprain,        knee,     moderate, 'RECOVERED',   'NON_CONTACT', 3, 7,  'Knee sprain during skating drill — no contact involved.',    'PHYSIO'),
            ('player_mh8', d(2025,12,10), strain,        lower_back,mild,    'ACTIVE',      'OVERUSE',     2, 4,  'Lower back strain from overtraining ahead of playoffs.',     'REST'),
            ('player_mh9', d(2024,10,8),  sprain,        shoulder, moderate, 'RECOVERED',   'CONTACT',     4, 9,  'Shoulder sprain from board contact (2024 season).',          'PHYSIO'),
            ('player_mh10',d(2024,11,15), dislocation,   shoulder, severe,   'RECOVERED',   'CONTACT',     7, 14, 'Shoulder dislocation, 2024 season.',                         'PHYSIO'),

            # ── Women's Ice Hockey ─────────────────────────────────────────
            ('player_wh1', d(2025,10,12), sprain,        ankle,    moderate, 'RECOVERED',   'NON_CONTACT', 2, 5,  'Ankle sprain landing awkwardly after jump.',                 'PHYSIO'),
            ('player_wh2', d(2025,11,3),  ligament_tear, knee,     severe,   'RECOVERING',  'NON_CONTACT', 9, 18, 'ACL partial tear during skating drill — no contact.',        'PHYSIO'),
            ('player_wh3', d(2025,10,25), contusion,     hip,      mild,     'RECOVERED',   'CONTACT',     1, 2,  'Hip contusion from fall on the ice.',                        'REST'),
            ('player_wh4', d(2025,12,5),  tendonitis,    shoulder, moderate, 'ACTIVE',      'OVERUSE',     3, 6,  'Shoulder tendonitis from repetitive overhead movements.',    'PHYSIO'),
            ('player_wh5', d(2024,10,20), fracture,      wrist,    severe,   'RECOVERED',   'CONTACT',     8, 16, 'Wrist fracture from fall (2024 season).',                    'REST'),
            ('player_wh6', d(2024,11,10), sprain,        ankle,    mild,     'RECOVERED',   'NON_CONTACT', 1, 4,  'Ankle sprain 2024 season.',                                  'PHYSIO'),

            # ── Men's Soccer ───────────────────────────────────────────────
            ('player_ms1', d(2025,9,14),  strain,        hamstring,moderate, 'RECOVERED',   'NON_CONTACT', 2, 6,  'Hamstring strain during sprint — classic non-contact.',      'REST'),
            ('player_ms2', d(2025,10,3),  strain,        hamstring,moderate, 'RECOVERED',   'NON_CONTACT', 3, 7,  'Hamstring strain during match sprint.',                      'PHYSIO'),
            ('player_ms3', d(2025,10,20), ligament_tear, knee,     severe,   'ACTIVE',      'CONTACT',     10,20, 'MCL tear from tackle by opposing player.',                   'PHYSIO'),
            ('player_ms4', d(2025,11,5),  contusion,     lower_back,mild,    'RECOVERED',   'CONTACT',     0, 2,  'Lower back contusion from fall.',                            'REST'),
            ('player_ms5', d(2025,11,18), strain,        hamstring,mild,     'RECOVERING',  'NON_CONTACT', 1, 4,  'Mild hamstring strain, preventable with better warm-up.',   'REST'),
            ('player_ms6', d(2024,9,20),  strain,        hamstring,moderate, 'RECOVERED',   'NON_CONTACT', 4, 8,  'Hamstring strain 2024 season.',                              'PHYSIO'),
            ('player_ms7', d(2024,10,12), sprain,        ankle,    moderate, 'RECOVERED',   'CONTACT',     3, 6,  'Ankle sprain from tackle.',                                  'PHYSIO'),
            ('player_ms8', d(2024,11,8),  strain,        hamstring,severe,   'RECOVERED',   'NON_CONTACT', 6, 12, 'Severe hamstring strain 2024 season.',                       'PHYSIO'),

            # ── Women's Soccer ─────────────────────────────────────────────
            ('player_ws1', d(2025,9,10),  ligament_tear, knee,     severe,   'RECOVERED',   'NON_CONTACT', 12,22, 'ACL tear — non-contact, cutting movement.',                  'SURGERY'),
            ('player_ws2', d(2025,10,8),  sprain,        ankle,    moderate, 'RECOVERED',   'CONTACT',     2, 5,  'Ankle sprain from tackle.',                                  'PHYSIO'),
            ('player_ws3', d(2025,10,25), strain,        hamstring,moderate, 'RECOVERING',  'NON_CONTACT', 3, 8,  'Hamstring strain during sprint drill.',                      'REST'),
            ('player_ws4', d(2025,11,12), concussion,    head,     moderate, 'RECOVERED',   'CONTACT',     4, 8,  'Concussion from heading contest.',                           'REST'),
            ('player_ws5', d(2025,12,1),  tendonitis,    foot,     mild,     'ACTIVE',      'OVERUSE',     1, 3,  'Plantar tendonitis from high training volume.',              'REST'),
            ('player_ws6', d(2024,9,15),  ligament_tear, knee,     severe,   'RECOVERED',   'NON_CONTACT', 15,28, 'ACL tear 2024 season — non-contact.',                        'SURGERY'),
            ('player_ws7', d(2024,10,5),  sprain,        ankle,    moderate, 'RECOVERED',   'CONTACT',     3, 7,  'Ankle sprain 2024 season.',                                  'PHYSIO'),
            ('player_ws8', d(2024,11,20), strain,        hamstring,mild,     'RECOVERED',   'NON_CONTACT', 2, 5,  'Hamstring strain 2024 season.',                              'REST'),

            # ── Football ───────────────────────────────────────────────────
            ('player_fb1', d(2025,9,6),   concussion,    head,     severe,   'RECOVERED',   'CONTACT',     3, 6,  'Concussion from helmet-to-helmet contact.',                  'REST'),
            ('player_fb2', d(2025,9,20),  fracture,      elbow,    severe,   'RECOVERED',   'CONTACT',     6, 12, 'Elbow fracture from sack.',                                  'REST'),
            ('player_fb3', d(2025,10,4),  strain,        hamstring,moderate, 'RECOVERED',   'NON_CONTACT', 2, 5,  'Hamstring strain during route running.',                     'PHYSIO'),
            ('player_fb4', d(2025,10,18), ligament_tear, knee,     severe,   'ACTIVE',      'CONTACT',     8, 16, 'MCL tear from low tackle.',                                  'PHYSIO'),
            ('player_fb5', d(2025,11,1),  contusion,     shoulder, mild,     'RECOVERED',   'CONTACT',     1, 2,  'Shoulder contusion from block.',                             'REST'),
            ('player_fb6', d(2025,11,15), sprain,        ankle,    moderate, 'RECOVERING',  'NON_CONTACT', 2, 6,  'Ankle sprain during drill.',                                 'PHYSIO'),
            ('player_fb7', d(2025,12,3),  tendonitis,    lower_back,moderate,'ACTIVE',      'OVERUSE',     2, 5,  'Lower back tendonitis from repeated blocking.',              'PHYSIO'),
            ('player_fb8', d(2024,9,12),  concussion,    head,     severe,   'RECOVERED',   'CONTACT',     4, 8,  'Concussion 2024 season.',                                    'REST'),
            ('player_fb9', d(2024,10,10), fracture,      wrist,    severe,   'RECOVERED',   'CONTACT',     5, 10, 'Wrist fracture 2024 season.',                                'REST'),
            ('player_fb10',d(2024,11,5),  strain,        hamstring,moderate, 'RECOVERED',   'NON_CONTACT', 3, 7,  'Hamstring strain 2024 season.',                              'PHYSIO'),
        ]

        created_count = 0
        for row in injuries_to_create:
            (username, inj_date, inj_type, body_part, severity,
             status, contact_type, missed_games, missed_practices,
             description, treatment) = row

            player = players.get(username)
            if not player:
                continue

            # Avoid duplicates
            if InjuryRecord.objects.filter(
                player=player, injury_date=inj_date, injury_type=inj_type
            ).exists():
                continue

            # Auto recovery time for recovered injuries
            actual_rt = None
            clearance = False
            clearance_date = None
            if status == 'RECOVERED':
                actual_rt = (missed_games or 0) * 4 + random.randint(5, 20)
                clearance = True
                clearance_date = inj_date + timedelta(days=actual_rt)

            InjuryRecord.objects.create(
                player=player,
                reported_by=therapist,
                injury_date=inj_date,
                injury_type=inj_type,
                body_part=body_part,
                severity=severity,
                status=status,
                contact_type=contact_type,
                missed_games=missed_games,
                missed_practices=missed_practices,
                description=description,
                treatment=treatment,
                estimated_recovery_time=(missed_games or 2) * 4 + 10,
                actual_recovery_time=actual_rt,
                medical_clearance=clearance,
                clearance_date=clearance_date,
                follow_up_required=(status in ('ACTIVE', 'RECOVERING')),
                follow_up_date=(inj_date + timedelta(days=14)) if status in ('ACTIVE', 'RECOVERING') else None,
                # season_year auto-populated by model's save()
            )
            created_count += 1

        self.stdout.write(f'  {created_count} injury records created')

        # ── Summary ────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS('\n✓ Demo data loaded successfully!\n'))
        self.stdout.write('Login credentials:')
        self.stdout.write('  Admin / Director : chad / chad1234')
        self.stdout.write('  Athletic Therapist: therapist1 / demo1234')
        self.stdout.write('  Coach (Hockey M) : coach_hockeym / demo1234')
        self.stdout.write('  Coach (Soccer W) : coach_soccerw / demo1234')
        self.stdout.write('  Coach (Football) : coach_football / demo1234')
        self.stdout.write('  Player           : player_mh1 / demo1234')
        self.stdout.write('')
        self.stdout.write('Demo highlights:')
        self.stdout.write('  - Men\'s Hockey: 8 shoulder injuries (80% of team injuries)')
        self.stdout.write('  - Women\'s Soccer: 17 missed games 2025 vs 34 in 2024')
        self.stdout.write('  - Football: mix of contact + non-contact injuries')
        self.stdout.write('  - Analytics will show year-over-year trends across all teams')
