"""
injury_tracking/models.py — Team 12 updated version
Changes vs Team 13:
  - InjuryRecord: added contact_type, missed_games, missed_practices, season_year
  - InjuryRecord: added save() override to auto-populate season_year
  - InjuryRecord: added helper properties for reporting
Everything else is unchanged from Team 13.
"""

from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

User = get_user_model()


class Event(models.Model):
    """Team events such as trainings, sessions, and games"""
    EVENT_TYPE_CHOICES = [
        ('TRAINING', 'Training'),
        ('SESSION', 'Session'),
        ('GAME', 'Game'),
    ]

    team = models.ForeignKey('accounts.Team', on_delete=models.CASCADE, related_name='events')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_events')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_datetime']

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.title} ({self.start_datetime:%Y-%m-%d %H:%M})"


class InjuryType(models.Model):
    """Types of injuries that can occur"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class BodyPart(models.Model):
    """Body parts that can be injured"""
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class InjurySeverity(models.Model):
    """Severity levels for injuries"""
    name = models.CharField(max_length=50, unique=True)
    color_code = models.CharField(max_length=7, help_text="Hex color code (e.g., #FF0000)")
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class InjuryRecord(models.Model):
    """Main injury record model"""

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('RECOVERING', 'Recovering'),
        ('RECOVERED', 'Recovered'),
        ('CHRONIC', 'Chronic'),
    ]

    TREATMENT_CHOICES = [
        ('REST', 'Rest'),
        ('PHYSIO', 'Physiotherapy'),
        ('SURGERY', 'Surgery'),
        ('MEDICATION', 'Medication'),
        ('OTHER', 'Other'),
    ]

    # ------------------------------------------------------------------ #
    # NEW — Team 12 additions (Week 3)                                     #
    # ------------------------------------------------------------------ #
    CONTACT_TYPE_CHOICES = [
        ('CONTACT', 'Contact'),
        ('NON_CONTACT', 'Non-Contact'),
        ('OVERUSE', 'Overuse / Repetitive Strain'),
        ('UNKNOWN', 'Unknown'),
    ]

    INJURY_CONTEXT_CHOICES = [
        ('PRACTICE', 'Practice'),
        ('GAME', 'Game'),
        ('OTHER', 'Other'),
    ]

    COULD_KEEP_PLAYING_CHOICES = [
        ('YES', 'Yes'),
        ('NO', 'No'),
        ('STOPPED_LATER', 'Stopped later'),
    ]

    INJURY_NATURE_CHOICES = [
        ('bruise', 'Bruise'),
        ('twist', 'Twist'),
        ('pull', 'Pull'),
        ('impact', 'Impact'),
        ('cut', 'Cut'),
        ('other', 'Other'),
    ]

    contact_type = models.CharField(
        max_length=20,
        choices=CONTACT_TYPE_CHOICES,
        default='UNKNOWN',
        help_text=(
            "Contact = caused by contact with another player or object. "
            "Non-Contact = athlete's own movement, no external contact. "
            "Overuse = repetitive strain over time. "
            "Unknown = not yet classified."
        ),
    )

    missed_games = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of official games missed due to this injury.",
    )

    missed_practices = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Number of practices / training sessions missed due to this injury.",
    )

    season_year = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Academic season this injury belongs to "
            "(e.g. 2025 = the 2025–26 season). "
            "Auto-populated from injury_date if left blank."
        ),
    )
    # ------------------------------------------------------------------ #
    # END new fields                                                       #
    # ------------------------------------------------------------------ #

    # Basic Information — unchanged from Team 13
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='injuries')
    reported_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reported_injuries')
    injury_date = models.DateField()
    reported_date = models.DateTimeField(auto_now_add=True)

    # Injury Details
    injury_type = models.ForeignKey(InjuryType, on_delete=models.CASCADE)
    body_part = models.ForeignKey(BodyPart, on_delete=models.CASCADE)
    severity = models.ForeignKey(InjurySeverity, on_delete=models.CASCADE)
    injury_context = models.CharField(
        max_length=20,
        choices=INJURY_CONTEXT_CHOICES,
        null=True,
        blank=True,
    )
    could_keep_playing = models.CharField(
        max_length=20,
        choices=COULD_KEEP_PLAYING_CHOICES,
        null=True,
        blank=True,
    )
    pain_level = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )
    injury_nature = models.CharField(
        max_length=20,
        choices=INJURY_NATURE_CHOICES,
        null=True,
        blank=True,
    )
    photo = models.ImageField(upload_to='injury_photos/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')

    # Description and Notes
    description = models.TextField()
    symptoms = models.TextField(blank=True)
    treatment = models.CharField(max_length=20, choices=TREATMENT_CHOICES)
    treatment_notes = models.TextField(blank=True)

    # Recovery Information
    estimated_recovery_time = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Estimated recovery time in days",
    )
    actual_recovery_time = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Actual recovery time in days",
    )
    return_to_play_date = models.DateField(null=True, blank=True)

    # Medical Information
    requires_surgery = models.BooleanField(default=False)
    surgery_date = models.DateField(null=True, blank=True)
    medical_clearance = models.BooleanField(default=False)
    clearance_date = models.DateField(null=True, blank=True)

    # Follow-up
    follow_up_required = models.BooleanField(default=False)
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_notes = models.TextField(blank=True)

    # Metadata
    is_confidential = models.BooleanField(default=False)
    self_reported = models.BooleanField(
        default=False,
        help_text="True if reported directly by the player (pending therapist review).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-injury_date']
        permissions = [
            ("view_own_injuries", "Can view own injuries"),
            ("view_team_injuries", "Can view team injuries"),
            ("view_all_injuries", "Can view all injuries"),
        ]

    # ------------------------------------------------------------------ #
    # NEW — auto-populate season_year on save                             #
    # ------------------------------------------------------------------ #
    def save(self, *args, **kwargs):
        """
        Auto-populate season_year from injury_date if not explicitly set.

        Convention: the academic season starts in September.
        - An injury in Oct 2025 → season_year = 2025  (2025–26 season)
        - An injury in Feb 2026 → season_year = 2025  (still 2025–26)
        - An injury in Sep 2026 → season_year = 2026  (2026–27 season)
        """
        if self.season_year is None and self.injury_date:
            month = self.injury_date.month
            year = self.injury_date.year
            # Months Jan–Aug belong to the previous academic year's season
            self.season_year = year if month >= 9 else year - 1
        super().save(*args, **kwargs)
    # ------------------------------------------------------------------ #

    def __str__(self):
        return f"{self.player.get_full_name()} - {self.injury_type.name} ({self.injury_date})"

    @property
    def days_since_injury(self):
        """Calculate days since injury occurred"""
        return (timezone.now().date() - self.injury_date).days

    @property
    def is_fully_recovered(self):
        """Check if player is fully recovered"""
        return self.status == 'RECOVERED' and self.medical_clearance

    # ------------------------------------------------------------------ #
    # NEW — helper properties used by reporting views                     #
    # ------------------------------------------------------------------ #
    @property
    def is_preventable(self):
        """Non-contact and overuse injuries are considered potentially preventable."""
        return self.contact_type in ('NON_CONTACT', 'OVERUSE')

    @property
    def total_missed_events(self):
        """Combined games + practices missed. Returns None if both are unset."""
        games = self.missed_games or 0
        practices = self.missed_practices or 0
        if self.missed_games is None and self.missed_practices is None:
            return None
        return games + practices
    # ------------------------------------------------------------------ #


class InjuryFollowUp(models.Model):
    """Follow-up records for injuries"""
    injury = models.ForeignKey(InjuryRecord, on_delete=models.CASCADE, related_name='follow_ups')
    follow_up_date = models.DateField()
    notes = models.TextField()
    status_update = models.CharField(max_length=20, choices=InjuryRecord.STATUS_CHOICES)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Follow-up for {self.injury} on {self.follow_up_date}"


class TeamRoster(models.Model):
    """Team roster management"""
    team = models.ForeignKey('accounts.Team', on_delete=models.CASCADE, related_name='roster')
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name='team_memberships')
    position = models.CharField(max_length=50, blank=True)
    jersey_number = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    joined_date = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ['team', 'player']

    def __str__(self):
        return f"{self.player.get_full_name()} - {self.team.name}"


class Appointment(models.Model):
    """Player-requested appointment with a team therapist/doctor."""
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('CONFIRMED', 'Confirmed'),
        ('CANCELLED', 'Cancelled'),
        ('COMPLETED', 'Completed'),
    ]

    TIME_SLOT_CHOICES = [
        ('MORNING', 'Morning (9 AM - 12 PM)'),
        ('AFTERNOON', 'Afternoon (12 PM - 5 PM)'),
        ('EVENING', 'Evening (5 PM - 7 PM)'),
    ]

    player = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='appointments',
        limit_choices_to={'role': 'PLAYER'},
    )
    therapist = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='therapist_appointments',
        help_text="Doctor / therapist assigned to handle the appointment.",
    )
    team = models.ForeignKey(
        'accounts.Team', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='appointments',
    )
    preferred_date = models.DateField()
    preferred_time_slot = models.CharField(max_length=20, choices=TIME_SLOT_CHOICES)
    confirmed_datetime = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['preferred_date', 'created_at']
        indexes = [
            models.Index(fields=['player', 'status']),
            models.Index(fields=['preferred_date']),
        ]

    def __str__(self):
        return f"{self.player.get_full_name() or self.player.username} - {self.preferred_date} ({self.get_status_display()})"


class InjuryAnalytics(models.Model):
    """Analytics data for injury tracking"""
    team = models.ForeignKey('accounts.Team', on_delete=models.CASCADE)
    season_year = models.PositiveIntegerField()
    total_injuries = models.PositiveIntegerField(default=0)
    active_injuries = models.PositiveIntegerField(default=0)
    recovered_injuries = models.PositiveIntegerField(default=0)
    most_common_injury_type = models.ForeignKey(InjuryType, on_delete=models.SET_NULL, null=True)
    most_common_body_part = models.ForeignKey(BodyPart, on_delete=models.SET_NULL, null=True)
    average_recovery_time = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['team', 'season_year']

    def __str__(self):
        return f"{self.team.name} - {self.season_year} Analytics"
