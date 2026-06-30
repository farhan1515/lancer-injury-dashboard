from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.db.models import Q, Count, Avg, Sum
from django.http import JsonResponse
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.urls import reverse_lazy
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import datetime, timedelta
import json

from .models import (
    InjuryRecord, InjuryType, BodyPart, InjurySeverity,
    InjuryFollowUp, TeamRoster, InjuryAnalytics, Event, Appointment
)
from accounts.models import Notification
from accounts.utils import notify
from .forms import (
    InjuryReportForm, InjuryUpdateForm, InjuryFollowUpForm,
    PlayerProfileForm, TeamRosterForm, InjurySearchForm, EventForm,
    PlayerSelfReportForm
)
from accounts.models import CustomUser, Team

# Permission mixins
class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role == 'ADMIN'

class CoachRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role in ['ADMIN', 'COACH']

class DoctorRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role in ['ADMIN', 'DOCTOR']

class PlayerRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role in ['ADMIN', 'PLAYER']

# -------- Coach Events (Calendar) --------
@login_required
def events_calendar(request):
    """Calendar view for coaches to manage team events"""
    if request.user.role not in ['ADMIN', 'COACH']:
        messages.error(request, "Access denied. Coach privileges required.")
        return redirect('dashboard')
    if request.user.role == 'COACH' and not request.user.team:
        messages.error(request, "No team assigned. Please contact administrator.")
        return redirect('dashboard')

    # Upcoming events for quick view
    qs = Event.objects.all()
    if request.user.role == 'COACH':
        qs = qs.filter(team=request.user.team)
    upcoming_events = qs.order_by('start_datetime')[:10]

    return render(request, 'injury_tracking/events_calendar.html', {
        'upcoming_events': upcoming_events
    })

@login_required
def events_feed(request):
    """JSON feed for FullCalendar events for the coach's team"""
    if request.user.role not in ['ADMIN', 'COACH']:
        return JsonResponse({'error': 'Access denied'}, status=403)

    team = None
    if request.user.role == 'COACH':
        team = request.user.team
        if not team:
            return JsonResponse({'events': []})
    else:
        # Admin can pass team id
        team_id = request.GET.get('team')
        if team_id:
            team = get_object_or_404(Team, id=team_id)

    qs = Event.objects.all()
    if team:
        qs = qs.filter(team=team)

    # Optional range filtering by FullCalendar (start/end ISO strings)
    start = request.GET.get('start')
    end = request.GET.get('end')
    try:
        if start:
            start_dt = datetime.fromisoformat(start)
            qs = qs.filter(end_datetime__gte=start_dt)
        if end:
            end_dt = datetime.fromisoformat(end)
            qs = qs.filter(start_datetime__lte=end_dt)
    except Exception:
        pass

    events = []
    type_to_color = {
        'TRAINING': '#3b82f6',
        'SESSION': '#10b981',
        'GAME': '#f59e0b',
    }
    for ev in qs.order_by('start_datetime'):
        events.append({
            'id': ev.id,
            'title': ev.title,
            'start': ev.start_datetime.isoformat(),
            'end': ev.end_datetime.isoformat(),
            'url': str(reverse_lazy('tracking:event_detail', kwargs={'pk': ev.id})),
            'backgroundColor': type_to_color.get(ev.event_type, '#1f2937'),
            'borderColor': '#ffffff',
            'extendedProps': {
                'type': ev.get_event_type_display(),
                'location': ev.location or '',
            }
        })
    # Return a plain array as FullCalendar expects
    return JsonResponse(events, safe=False)

@login_required
def event_create(request):
    """Create a new event (coach/admin)"""
    if request.user.role not in ['ADMIN', 'COACH']:
        messages.error(request, "Access denied. Coach privileges required.")
        return redirect('dashboard')
    if request.method == 'POST':
        form = EventForm(request.POST, user=request.user)
        if form.is_valid():
            # Permission guard: selected team must be authorized
            selected_team = form.cleaned_data.get('team') if 'team' in form.cleaned_data else getattr(request.user, 'team', None)
            if request.user.role == 'COACH':
                auth_teams = request.user.get_authorized_teams() if hasattr(request.user, 'get_authorized_teams') else None
                if auth_teams is not None and selected_team and selected_team not in list(auth_teams):
                    messages.error(request, 'You do not have permission to create events for the selected team.')
                    return render(request, 'injury_tracking/event_form.html', {'form': form})
            event = form.save()
            # Fan-out notification to all players on the team
            link = str(reverse_lazy('tracking:event_detail', kwargs={'pk': event.id}))
            for player in CustomUser.objects.filter(role='PLAYER', team=event.team):
                notify(player,
                       f"New {event.get_event_type_display()}: {event.title} on {event.start_datetime:%b %d, %I:%M %p}",
                       notification_type='EVENT', link=link)
            messages.success(request, 'Event created successfully.')
            return redirect('tracking:event_detail', pk=event.id)
    else:
        # Pre-fill from query params (start/end/title) if provided by calendar selection
        initial = {}
        start_q = request.GET.get('start')
        end_q = request.GET.get('end')
        title_q = request.GET.get('title')
        if start_q:
            try:
                initial['start_datetime'] = datetime.fromisoformat(start_q)
            except Exception:
                pass
        if end_q:
            try:
                initial['end_datetime'] = datetime.fromisoformat(end_q)
            except Exception:
                pass
        if title_q:
            initial['title'] = title_q
        form = EventForm(user=request.user, initial=initial)
    return render(request, 'injury_tracking/event_form.html', {'form': form})

@login_required
def event_detail(request, pk):
    """Detail page for an event showing players expected to miss"""
    event = get_object_or_404(Event, pk=pk)

    # Permissions: coach of same team or admin
    if request.user.role == 'COACH':
        if not request.user.team or request.user.team != event.team:
            messages.error(request, "Access denied.")
            return redirect('dashboard')

    # Determine players likely to miss: active/recovering/chronic whose injury overlaps the event period
    overlapping_injuries = InjuryRecord.objects.filter(
        player__team=event.team,
        status__in=['ACTIVE', 'RECOVERING', 'CHRONIC'],
        injury_date__lte=event.end_datetime.date()
    ).select_related('player', 'injury_type', 'severity')

    # If return_to_play_date exists and is before event start, they should be available
    missing_players = []
    for inj in overlapping_injuries:
        rtp = inj.return_to_play_date
        if rtp and rtp < event.start_datetime.date():
            continue
        missing_players.append(inj)

    context = {
        'event': event,
        'missing_injuries': missing_players,
    }
    return render(request, 'injury_tracking/event_detail.html', context)

# Dashboard Views
@login_required
def dashboard(request):
    """Redirect to appropriate dashboard based on user role"""
    user = request.user
    
    # Check if user has completed registration
    if not user.is_registration_complete:
        return redirect('complete_registration')
    
    if user.role == 'ADMIN':
        return redirect('admin_dashboard')
    elif user.role == 'COACH':
        return redirect('coach_dashboard')
    elif user.role == 'DOCTOR':
        return redirect('doctor_dashboard')
    elif user.role == 'PLAYER':
        return redirect('player_dashboard')
    else:
        return redirect('login')

@login_required
def admin_dashboard(request):
    """Admin dashboard with comprehensive analytics"""
    # Check if user has completed registration
    if not request.user.is_registration_complete:
        return redirect('complete_registration')
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied. Admin privileges required.")
        return redirect('dashboard')
    
    # Get analytics data
    total_players = CustomUser.objects.filter(role='PLAYER').count()
    total_injuries = InjuryRecord.objects.count()
    active_injuries = InjuryRecord.objects.filter(status='ACTIVE').count()
    recovered_injuries = InjuryRecord.objects.filter(status='RECOVERED').count()
    
    # Recent injuries
    recent_injuries = InjuryRecord.objects.select_related(
        'player', 'injury_type', 'severity'
    ).order_by('-reported_date')[:10]
    
    # Team-wise statistics
    team_stats = []
    for team in Team.objects.all():
        team_injuries = InjuryRecord.objects.filter(player__team=team)
        team_stats.append({
            'team': team,
            'total_injuries': team_injuries.count(),
            'active_injuries': team_injuries.filter(status='ACTIVE').count(),
            'players': CustomUser.objects.filter(role='PLAYER', team=team).count()
        })
    
    # Injury type distribution
    injury_type_stats = InjuryRecord.objects.values('injury_type__name').annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    # Body part distribution
    body_part_stats = InjuryRecord.objects.values('body_part__name').annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    context = {
        'total_players': total_players,
        'total_injuries': total_injuries,
        'active_injuries': active_injuries,
        'recovered_injuries': recovered_injuries,
        'recent_injuries': recent_injuries,
        'team_stats': team_stats,
        'injury_type_stats': injury_type_stats,
        'body_part_stats': body_part_stats,
    }
    
    return render(request, 'accounts/admin_dashboard.html', context)

@login_required
def coach_dashboard(request):
    """Coach dashboard with team player status"""
    # Check if user has completed registration
    if not request.user.is_registration_complete:
        return redirect('complete_registration')
    
    if request.user.role not in ['ADMIN', 'COACH']:
        messages.error(request, "Access denied. Coach privileges required.")
        return redirect('dashboard')
    
    user = request.user
    team = user.team
    
    if not team:
        messages.error(request, "No team assigned. Please contact administrator.")
        return redirect('dashboard')
    
    # Get team players with their injury status
    players = CustomUser.objects.filter(role='PLAYER', team=team).select_related('playerprofile')
    
    player_status = []
    for player in players:
        active_injuries = InjuryRecord.objects.filter(
            player=player, status='ACTIVE'
        ).select_related('injury_type', 'severity')
        
        latest_injury = active_injuries.first()
        
        # Determine status color
        if latest_injury:
            if latest_injury.severity.name == 'Severe':
                status_color = 'danger'
            elif latest_injury.severity.name == 'Moderate':
                status_color = 'warning'
            else:
                status_color = 'info'
        else:
            status_color = 'success'
        
        player_status.append({
            'player': player,
            'active_injuries': active_injuries,
            'latest_injury': latest_injury,
            'status_color': status_color,
            'total_injuries': InjuryRecord.objects.filter(player=player).count()
        })
    
    # Team injury statistics
    team_injuries = InjuryRecord.objects.filter(player__team=team)
    active_count = team_injuries.filter(status='ACTIVE').count()
    recovered_count = team_injuries.filter(status='RECOVERED').count()
    
    # Recent team injuries (last 10)
    recent_injuries = team_injuries.select_related(
        'player', 'injury_type', 'body_part', 'severity', 'reported_by'
    ).order_by('-injury_date')[:10]
    
    context = {
        'team': team,
        'player_status': player_status,
        'active_count': active_count,
        'recovered_count': recovered_count,
        'total_players': players.count(),
        'recent_injuries': recent_injuries,
    }
    
    return render(request, 'accounts/coach_dashboard.html', context)

@login_required
def doctor_dashboard(request):
    """Doctor dashboard for injury management"""
    # Check if user has completed registration
    if not request.user.is_registration_complete:
        return redirect('complete_registration')
    
    if request.user.role not in ['ADMIN', 'DOCTOR']:
        messages.error(request, "Access denied. Doctor privileges required.")
        return redirect('dashboard')
    
    # Get recent injuries that need attention
    # Exclude injuries that have been medically cleared (cleared injuries don't need attention)
    recent_injuries = InjuryRecord.objects.filter(
        status__in=['ACTIVE', 'RECOVERING'],
        medical_clearance=False  # Only show injuries that haven't been cleared
    ).select_related('player', 'injury_type', 'severity').order_by('-reported_date')[:10]
    
    # Get follow-ups due
    # Exclude injuries that have been medically cleared
    today = timezone.now().date()
    follow_ups_due = InjuryRecord.objects.filter(
        follow_up_required=True,
        follow_up_date__lte=today,
        status__in=['ACTIVE', 'RECOVERING'],
        medical_clearance=False  # Only show injuries that haven't been cleared
    ).select_related('player', 'injury_type')
    
    # Get pending clearances (injuries marked as RECOVERED but not yet medically cleared)
    pending_clearances = InjuryRecord.objects.filter(
        status='RECOVERED',
        medical_clearance=False
    ).select_related('player', 'injury_type')
    
    context = {
        'recent_injuries': recent_injuries,
        'follow_ups_due': follow_ups_due,
        'pending_clearances': pending_clearances,
    }
    
    return render(request, 'accounts/doctor_dashboard.html', context)

@login_required
def player_dashboard(request):
    """Player overview dashboard."""
    if not request.user.is_registration_complete:
        return redirect('complete_registration')

    if request.user.role not in ['ADMIN', 'PLAYER']:
        messages.error(request, "Access denied. Player privileges required.")
        return redirect('dashboard')

    user = request.user
    today = timezone.now().date()

    # Current (non-recovered) injuries — shown on the overview cards
    current_injuries = InjuryRecord.objects.filter(
        player=user
    ).exclude(status='RECOVERED').select_related(
        'injury_type', 'body_part', 'severity'
    ).order_by('-injury_date')

    # Upcoming appointments (next 5)
    upcoming_appointments = Appointment.objects.filter(
        player=user,
        preferred_date__gte=today,
    ).exclude(status='CANCELLED').select_related('therapist', 'team').order_by('preferred_date')[:5]

    # Notifications
    unread_notifications = Notification.objects.filter(user=user, is_read=False).count()

    # ---------- Clearance status ----------
    active_count_player = current_injuries.filter(status='ACTIVE').count()
    recovering_count_player = current_injuries.filter(status='RECOVERING').count()
    has_any_injury = InjuryRecord.objects.filter(player=user).exists()

    if not has_any_injury:
        clearance = {
            'state': 'ok',
            'title': 'All Clear',
            'subtitle': 'No injuries on record',
            'icon': 'bi-check-circle-fill',
            'border_color': '#10b981',
            'icon_color': '#10b981',
            'bg_color': 'rgba(16, 185, 129, 0.10)',
            'clearance_date': None,
            'foot_note': '',
        }
    elif active_count_player > 0:
        clearance = {
            'state': 'active',
            'title': 'Not Cleared to Play',
            'subtitle': (
                f"You have {active_count_player} active "
                f"{'injury' if active_count_player == 1 else 'injuries'} requiring attention"
            ),
            'icon': 'bi-x-circle-fill',
            'border_color': '#ef4444',
            'icon_color': '#ef4444',
            'bg_color': 'rgba(239, 68, 68, 0.10)',
            'clearance_date': None,
            'foot_note': 'A therapist must review and clear you before returning to play.',
        }
    elif recovering_count_player > 0:
        clearance = {
            'state': 'recovering',
            'title': 'Recovery in Progress',
            'subtitle': (
                f"You have {recovering_count_player} "
                f"{'injury' if recovering_count_player == 1 else 'injuries'} being monitored"
            ),
            'icon': 'bi-exclamation-triangle-fill',
            'border_color': '#f59e0b',
            'icon_color': '#f59e0b',
            'bg_color': 'rgba(245, 158, 11, 0.10)',
            'clearance_date': None,
            'foot_note': 'Contact your therapist if symptoms worsen.',
        }
    else:
        last_cleared = InjuryRecord.objects.filter(
            player=user, medical_clearance=True, clearance_date__isnull=False
        ).order_by('-clearance_date').first()
        clearance = {
            'state': 'ok',
            'title': 'Cleared to Play',
            'subtitle': 'All injuries resolved — medical clearance granted',
            'icon': 'bi-check-circle-fill',
            'border_color': '#10b981',
            'icon_color': '#10b981',
            'bg_color': 'rgba(16, 185, 129, 0.10)',
            'clearance_date': last_cleared.clearance_date if last_cleared else None,
            'foot_note': '',
        }

    # ---------- Season stats ----------
    current_year = today.year
    season_qs = InjuryRecord.objects.filter(player=user, injury_date__year=current_year)
    total_missed_games = season_qs.aggregate(s=Sum('missed_games'))['s'] or 0
    total_missed_practices = season_qs.aggregate(s=Sum('missed_practices'))['s'] or 0
    active_recovery_days = (
        InjuryRecord.objects.filter(player=user)
        .exclude(status='RECOVERED')
        .aggregate(s=Sum('estimated_recovery_time'))['s'] or 0
    )

    context = {
        'current_injuries': current_injuries,
        'upcoming_appointments': upcoming_appointments,
        'unread_notifications': unread_notifications,
        'clearance': clearance,
        'total_missed_games': total_missed_games,
        'total_missed_practices': total_missed_practices,
        'active_recovery_days': active_recovery_days,
    }

    return render(request, 'accounts/player_dashboard.html', context)

# ---------------- Doctor: pending self-reported injuries ----------------

@login_required
def pending_review_inbox(request):
    """Doctor inbox of self-reported injuries awaiting triage."""
    if request.user.role not in ['ADMIN', 'DOCTOR']:
        messages.error(request, "Doctor access required.")
        return redirect('dashboard')

    pending = InjuryRecord.objects.filter(
        self_reported=True, status='ACTIVE'
    ).select_related('player', 'body_part', 'injury_type', 'severity').order_by('-reported_date')

    return render(request, 'injury_tracking/pending_review_inbox.html', {
        'pending': pending,
    })


# ---------------- Coach / Doctor: appointment inbox ----------------

def _appointments_in_scope(user):
    """Appointments the given user is allowed to see/act on."""
    qs = Appointment.objects.select_related('player', 'therapist', 'team').order_by('preferred_date')
    if user.role == 'ADMIN':
        return qs
    teams = list(user.get_authorized_teams()) if hasattr(user, 'get_authorized_teams') else []
    if user.team and user.team not in teams:
        teams.append(user.team)
    if not teams:
        return qs.none()
    return qs.filter(team__in=teams)


@login_required
def appointment_inbox(request):
    """List of appointments for the user's authorized team(s)."""
    if request.user.role not in ['ADMIN', 'COACH', 'DOCTOR']:
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    status_filter = request.GET.get('status', 'PENDING')
    qs = _appointments_in_scope(request.user)
    if status_filter and status_filter != 'ALL':
        qs = qs.filter(status=status_filter)
    return render(request, 'injury_tracking/appointment_inbox.html', {
        'appointments': qs,
        'status_filter': status_filter,
    })


@login_required
def appointment_decide(request, pk, decision):
    """Confirm or cancel an appointment; notifies the player."""
    if request.user.role not in ['ADMIN', 'COACH', 'DOCTOR']:
        messages.error(request, "Access denied.")
        return redirect('dashboard')
    if decision not in ('confirm', 'cancel'):
        messages.error(request, "Invalid action.")
        return redirect('tracking:appointment_inbox')

    appt = get_object_or_404(_appointments_in_scope(request.user), pk=pk)

    if decision == 'confirm':
        appt.status = 'CONFIRMED'
        if not appt.therapist and request.user.role == 'DOCTOR':
            appt.therapist = request.user
        if not appt.confirmed_datetime:
            appt.confirmed_datetime = timezone.now()
        appt.save()
        notify(appt.player,
               f"Your appointment on {appt.preferred_date:%b %d, %Y} ({appt.get_preferred_time_slot_display()}) was confirmed.",
               notification_type='APPOINTMENT')
        messages.success(request, f"Appointment for {appt.player.get_full_name()} confirmed.")
    else:
        appt.status = 'CANCELLED'
        appt.save()
        notify(appt.player,
               f"Your appointment request for {appt.preferred_date:%b %d, %Y} was cancelled.",
               notification_type='APPOINTMENT')
        messages.info(request, f"Appointment for {appt.player.get_full_name()} cancelled.")
    return redirect('tracking:appointment_inbox')


# Player self-service flows

def _default_injury_type():
    return InjuryType.objects.get_or_create(name='Pending Review')[0]


def _default_severity():
    return InjurySeverity.objects.first() or InjurySeverity.objects.create(
        name='Mild', color_code='#10b981', description='Minor injury'
    )


def _player_report_step(form):
    step_one_fields = {'body_part', 'injury_date', 'description'}
    return 1 if step_one_fields.intersection(form.errors.keys()) else 2


@login_required
def player_report_injury(request):
    """Render the dedicated player injury self-report wizard."""
    if request.user.role != 'PLAYER':
        messages.error(request, 'Only players can self-report injuries.')
        return redirect('dashboard')

    return render(request, 'injury_tracking/player_report_injury.html', {
        'form': PlayerSelfReportForm(),
        'current_step': 1,
    })


@login_required
def player_report_injury_submit(request):
    """Persist a player self-reported injury from the dedicated wizard page."""
    if request.user.role != 'PLAYER':
        messages.error(request, "Only players can self-report injuries.")
        return redirect('dashboard')
    if request.method != 'POST':
        return redirect('tracking:player_report_injury')

    form = PlayerSelfReportForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, 'injury_tracking/player_report_injury.html', {
            'form': form,
            'current_step': _player_report_step(form),
        })

    injury = InjuryRecord.objects.create(
        player=request.user,
        reported_by=request.user,
        injury_type=_default_injury_type(),
        severity=_default_severity(),
        status='ACTIVE',
        treatment='REST',
        self_reported=True,
        **form.cleaned_data,
    )
    messages.success(
        request,
        'Injury reported successfully. A therapist will review your report shortly.',
    )
    return redirect('tracking:injury_detail', pk=injury.pk)


@login_required
def player_request_appointment_submit(request):
    """Player books an appointment with their team therapist."""
    if request.user.role != 'PLAYER':
        messages.error(request, "Only players can request appointments.")
        return redirect('dashboard')
    if request.method != 'POST':
        return redirect('tracking:player_dashboard')

    preferred_date_str = request.POST.get('preferred_date')
    preferred_time_slot = request.POST.get('preferred_time_slot')
    note = (request.POST.get('note') or '').strip()

    if not preferred_date_str or not preferred_time_slot:
        messages.error(request, "Please pick a date and time slot.")
        return redirect('tracking:player_dashboard')

    try:
        preferred_date = datetime.strptime(preferred_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        messages.error(request, "Invalid date.")
        return redirect('tracking:player_dashboard')

    if preferred_date < timezone.now().date():
        messages.error(request, "Date cannot be in the past.")
        return redirect('tracking:player_dashboard')

    valid_slots = {k for k, _ in Appointment.TIME_SLOT_CHOICES}
    if preferred_time_slot not in valid_slots:
        messages.error(request, "Invalid time slot.")
        return redirect('tracking:player_dashboard')

    # Try to find a therapist (DOCTOR) linked to the player's team via TeamPermission
    therapist = None
    team = getattr(request.user, 'team', None)
    if team:
        from accounts.models import TeamPermission
        tp = TeamPermission.objects.filter(
            team=team, role_scope='DOCTOR'
        ).select_related('user').first()
        if tp:
            therapist = tp.user
        else:
            therapist = CustomUser.objects.filter(role='DOCTOR', team=team).first()

    appt = Appointment.objects.create(
        player=request.user,
        therapist=therapist,
        team=team,
        preferred_date=preferred_date,
        preferred_time_slot=preferred_time_slot,
        note=note,
        status='PENDING',
    )
    # Notify the assigned therapist (if any) about the new request
    if therapist:
        notify(therapist,
               f"New appointment request from {request.user.get_full_name() or request.user.username} "
               f"for {appt.preferred_date:%b %d, %Y} ({appt.get_preferred_time_slot_display()}).",
               notification_type='APPOINTMENT')
    messages.success(
        request,
        'Request sent — your therapist will confirm shortly.',
    )
    return redirect('tracking:player_dashboard')


# Injury Management Views
class InjuryListView(LoginRequiredMixin, ListView):
    """List view for injuries with filtering"""
    model = InjuryRecord
    template_name = 'injury_tracking/injury_list.html'
    context_object_name = 'injuries'
    paginate_by = 20
    
    def get_queryset(self):
        queryset = InjuryRecord.objects.select_related(
            'player', 'injury_type', 'body_part', 'severity', 'reported_by'
        ).order_by('-injury_date')
        
        # Apply role-based filtering
        user = self.request.user
        if user.role == 'PLAYER':
            queryset = queryset.filter(player=user)
        elif user.role == 'COACH' and user.team:
            queryset = queryset.filter(player__team=user.team)
        elif user.role == 'DOCTOR':
            # Doctors can see all injuries
            pass
        elif user.role != 'ADMIN':
            queryset = queryset.none()
        
        # Apply search filters
        search_form = InjurySearchForm(self.request.GET)
        if search_form.is_valid():
            if search_form.cleaned_data.get('player'):
                queryset = queryset.filter(player=search_form.cleaned_data['player'])
            if search_form.cleaned_data.get('injury_type'):
                queryset = queryset.filter(injury_type=search_form.cleaned_data['injury_type'])
            if search_form.cleaned_data.get('body_part'):
                queryset = queryset.filter(body_part=search_form.cleaned_data['body_part'])
            if search_form.cleaned_data.get('severity'):
                queryset = queryset.filter(severity=search_form.cleaned_data['severity'])
            if search_form.cleaned_data.get('status'):
                queryset = queryset.filter(status=search_form.cleaned_data['status'])
            if search_form.cleaned_data.get('date_from'):
                queryset = queryset.filter(injury_date__gte=search_form.cleaned_data['date_from'])
            if search_form.cleaned_data.get('date_to'):
                queryset = queryset.filter(injury_date__lte=search_form.cleaned_data['date_to'])
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = InjurySearchForm(self.request.GET)
        return context

class InjuryDetailView(LoginRequiredMixin, DetailView):
    """Detail view for individual injuries"""
    model = InjuryRecord
    template_name = 'injury_tracking/injury_detail.html'
    context_object_name = 'injury'
    
    def get_queryset(self):
        queryset = InjuryRecord.objects.select_related(
            'player', 'injury_type', 'body_part', 'severity', 'reported_by'
        )
        
        # Apply role-based filtering
        user = self.request.user
        if user.role == 'PLAYER':
            queryset = queryset.filter(player=user)
        elif user.role == 'COACH' and user.team:
            queryset = queryset.filter(player__team=user.team)
        elif user.role == 'DOCTOR':
            # Doctors can see all injuries
            pass
        elif user.role != 'ADMIN':
            queryset = queryset.none()
        
        return queryset

class InjuryCreateView(DoctorRequiredMixin, CreateView):
    """Create new injury report"""
    model = InjuryRecord
    form_class = InjuryReportForm
    template_name = 'injury_tracking/injury_form.html'
    success_url = reverse_lazy('injury_list')
    
    def form_valid(self, form):
        form.instance.reported_by = self.request.user
        messages.success(self.request, 'Injury report created successfully.')
        return super().form_valid(form)
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

class InjuryUpdateView(DoctorRequiredMixin, UpdateView):
    """Update injury record"""
    model = InjuryRecord
    form_class = InjuryUpdateForm
    template_name = 'injury_tracking/injury_update_form.html'

    def form_valid(self, form):
        # Snapshot pre-save state so we know what to notify about
        old = InjuryRecord.objects.get(pk=form.instance.pk)
        was_self_reported = old.self_reported
        old_status = old.status
        old_clearance = old.medical_clearance

        # Get medical clearance status from form
        medical_clearance = form.cleaned_data.get('medical_clearance', False)
        status = form.cleaned_data.get('status')

        # Modify the instance directly (form.instance is a reference to the actual model instance)
        injury = form.instance

        # If medical clearance is checked, automatically set status to RECOVERED if not already
        if medical_clearance and status != 'RECOVERED':
            injury.status = 'RECOVERED'

        # Auto-calculate actual recovery time if status is RECOVERED or medical clearance is set
        if injury.status == 'RECOVERED' or medical_clearance:
            if not injury.actual_recovery_time:
                recovery_days = (timezone.now().date() - injury.injury_date).days
                if recovery_days > 0:
                    injury.actual_recovery_time = recovery_days
            if medical_clearance and not injury.clearance_date:
                injury.clearance_date = timezone.now().date()

        # A doctor touching a self-reported record means it has been triaged.
        if was_self_reported:
            injury.self_reported = False

        response = super().form_valid(form)

        # ---- Notifications to the player ----
        link = reverse_lazy('tracking:injury_detail', kwargs={'pk': injury.pk}).__str__()
        if was_self_reported:
            notify(injury.player,
                   f"Your self-reported {injury.body_part.name} injury has been reviewed by a therapist.",
                   notification_type='INJURY', link=link)
        if medical_clearance and not old_clearance:
            notify(injury.player,
                   f"Medical clearance granted for your {injury.body_part.name} injury — you're cleared to play.",
                   notification_type='CLEARANCE', link=link)
        elif status and status != old_status:
            notify(injury.player,
                   f"Your {injury.body_part.name} injury status changed to {injury.get_status_display()}.",
                   notification_type='INJURY', link=link)

        messages.success(self.request, f'Injury record for {injury.player.get_full_name()} has been updated successfully.')
        if medical_clearance:
            messages.info(self.request, 'Player has been medically cleared. Injury removed from active dashboard.')

        return response
    
    def get_success_url(self):
        from django.urls import reverse
        return reverse('tracking:injury_detail', kwargs={'pk': self.object.pk})

# Analytics Views
@login_required
def analytics_dashboard(request):
    """Analytics dashboard for injury data visualization
    IMPORTANT: This view includes ALL injuries regardless of status (ACTIVE, RECOVERING, RECOVERED, CHRONIC)
    to ensure comprehensive tracking and analysis for end-of-year reports.
    """
    # Check if user has completed registration
    if not request.user.is_registration_complete:
        return redirect('complete_registration')
    
    if request.user.role not in ['ADMIN', 'COACH']:
        messages.error(request, "Access denied. Admin or Coach privileges required.")
        return redirect('dashboard')
    
    # Get date range filters (for academic year analysis)
    # Default to current year, but allow filtering by academic year
    selected_year = request.GET.get('year', str(timezone.now().year))
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    try:
        selected_year = int(selected_year)
    except (ValueError, TypeError):
        selected_year = timezone.now().year
    
    # Get team filter
    team_filter = None
    if request.user.role == 'COACH' and request.user.team:
        team_filter = request.user.team
    elif request.GET.get('team'):
        team_filter = get_object_or_404(Team, id=request.GET.get('team'))
    
    # Build base queryset - INCLUDES ALL INJURIES (ACTIVE, RECOVERING, RECOVERED, CHRONIC)
    # This is critical for comprehensive tracking and end-of-year analysis
    if team_filter:
        injuries_queryset = InjuryRecord.objects.filter(player__team=team_filter)
    else:
        injuries_queryset = InjuryRecord.objects.all()
    
    # Apply date range filtering if provided
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            injuries_queryset = injuries_queryset.filter(injury_date__gte=date_from_obj)
        except (ValueError, TypeError):
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            injuries_queryset = injuries_queryset.filter(injury_date__lte=date_to_obj)
        except (ValueError, TypeError):
            pass
    
    # If no date range specified, filter by selected year
    if not date_from and not date_to:
        injuries_queryset = injuries_queryset.filter(injury_date__year=selected_year)

    # Additional filters: contact_type and status
    contact_type_filter = request.GET.get('contact_type')
    status_filter = request.GET.get('status')
    if contact_type_filter:
        injuries_queryset = injuries_queryset.filter(contact_type=contact_type_filter)
    if status_filter:
        injuries_queryset = injuries_queryset.filter(status=status_filter)

    # Status breakdown - show that ALL injuries including recovered are included
    status_breakdown = injuries_queryset.values('status').annotate(
        count=Count('id')
    ).order_by('status')
    
    # Monthly injury trends (includes ALL statuses) with player details
    monthly_data = []
    monthly_injuries_detail = []  # Store detailed injury info for each month
    for month in range(1, 13):
        month_injuries_qs = injuries_queryset.filter(
            injury_date__year=selected_year,
            injury_date__month=month
        ).select_related('player', 'injury_type', 'body_part', 'severity')
        
        month_injuries = month_injuries_qs.count()
        
        # Get detailed injury info for this month
        month_details = []
        for injury in month_injuries_qs:
            month_details.append({
                'player': injury.player.get_full_name() or injury.player.username,
                'injury_type': injury.injury_type.name,
                'body_part': injury.body_part.name,
                'severity': injury.severity.name,
                'status': injury.status,
                'date': injury.injury_date.strftime('%Y-%m-%d'),
            })
        
        monthly_data.append({
            'month': month,
            'count': month_injuries
        })
        monthly_injuries_detail.append({
            'month': month,
            'injuries': month_details
        })
    
    # Injury type distribution (includes ALL injuries regardless of status)
    injury_type_data = injuries_queryset.values('injury_type__name').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Get detailed injury type data with player info
    injury_type_details = {}
    for injury_type_name in [item['injury_type__name'] for item in injury_type_data]:
        type_injuries = injuries_queryset.filter(
            injury_type__name=injury_type_name
        ).select_related('player', 'body_part', 'severity')
        injury_type_details[injury_type_name] = [
            {
                'player': inj.player.get_full_name() or inj.player.username,
                'body_part': inj.body_part.name,
                'severity': inj.severity.name,
                'status': inj.status,
                'date': inj.injury_date.strftime('%Y-%m-%d'),
            }
            for inj in type_injuries
        ]
    
    # Body part distribution (includes ALL injuries regardless of status)
    body_part_data = injuries_queryset.values('body_part__name').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Get detailed body part data with player info
    body_part_details = {}
    for body_part_name in [item['body_part__name'] for item in body_part_data]:
        part_injuries = injuries_queryset.filter(
            body_part__name=body_part_name
        ).select_related('player', 'injury_type', 'severity')
        body_part_details[body_part_name] = [
            {
                'player': inj.player.get_full_name() or inj.player.username,
                'injury_type': inj.injury_type.name,
                'severity': inj.severity.name,
                'status': inj.status,
                'date': inj.injury_date.strftime('%Y-%m-%d'),
            }
            for inj in part_injuries
        ]
    
    # Severity distribution (includes ALL injuries regardless of status)
    severity_data = injuries_queryset.values('severity__name', 'severity__color_code').annotate(
        count=Count('id')
    ).order_by('-count')

    # Body part counts (per-status) for the interactive Body Map component
    body_part_counts_raw = injuries_queryset.values('body_part__name').annotate(
        count=Count('id'),
        active=Count('id', filter=Q(status='ACTIVE')),
        recovering=Count('id', filter=Q(status='RECOVERING')),
        recovered=Count('id', filter=Q(status='RECOVERED')),
    )
    body_part_counts = {
        row['body_part__name']: {
            'count': row['count'],
            'active': row['active'],
            'recovering': row['recovering'],
            'recovered': row['recovered'],
        }
        for row in body_part_counts_raw if row['body_part__name']
    }
    
    # Get all injuries with player details for detailed breakdown table
    all_injuries_detail = injuries_queryset.select_related(
        'player', 'injury_type', 'body_part', 'severity'
    ).order_by('-injury_date')
    active_injuries_detail = all_injuries_detail.filter(status='ACTIVE')
    recovered_injuries_detail = all_injuries_detail.filter(status='RECOVERED')
    
    # Recovery time analysis (only for recovered injuries with actual recovery time)
    recovered_injuries = injuries_queryset.filter(
        status='RECOVERED',
        actual_recovery_time__isnull=False
    )
    avg_recovery_time = recovered_injuries.aggregate(avg_time=Avg('actual_recovery_time'))['avg_time']
    
    # Total statistics (ALL injuries included)
    total_injuries = injuries_queryset.count()
    active_count = injuries_queryset.filter(status='ACTIVE').count()
    recovering_count = injuries_queryset.filter(status='RECOVERING').count()
    recovered_count = injuries_queryset.filter(status='RECOVERED').count()
    chronic_count = injuries_queryset.filter(status='CHRONIC').count()
    
    # Team comparison (for admins) - includes ALL injuries
    team_comparison = []
    if request.user.role == 'ADMIN':
        for team in Team.objects.all():
            # Apply same date filters to team comparison
            team_injuries = InjuryRecord.objects.filter(player__team=team)
            if date_from:
                try:
                    from datetime import datetime
                    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                    team_injuries = team_injuries.filter(injury_date__gte=date_from_obj)
                except (ValueError, TypeError):
                    pass
            if date_to:
                try:
                    from datetime import datetime
                    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                    team_injuries = team_injuries.filter(injury_date__lte=date_to_obj)
                except (ValueError, TypeError):
                    pass
            if not date_from and not date_to:
                team_injuries = team_injuries.filter(injury_date__year=selected_year)
            
            prev_year_injuries_count = InjuryRecord.objects.filter(
                player__team=team,
                injury_date__year=selected_year - 1,
            ).count()
            team_comparison.append({
                'team': team.name,
                'total_injuries': team_injuries.count(),  # ALL injuries
                'active_injuries': team_injuries.filter(status='ACTIVE').count(),
                'recovering_injuries': team_injuries.filter(status='RECOVERING').count(),
                'recovered_injuries': team_injuries.filter(status='RECOVERED').count(),
                'chronic_injuries': team_injuries.filter(status='CHRONIC').count(),
                'missed_games': team_injuries.aggregate(s=Sum('missed_games'))['s'] or 0,
                'missed_practices': team_injuries.aggregate(s=Sum('missed_practices'))['s'] or 0,
                'prev_year_injuries': prev_year_injuries_count,
            })
    
    # Get available years for dropdown (from injury dates in database)
    available_years = sorted(
        set(InjuryRecord.objects.values_list('injury_date__year', flat=True).distinct()),
        reverse=True
    )
    if not available_years:
        available_years = [timezone.now().year]

    # Contact type distribution
    contact_type_label_map = dict(InjuryRecord.CONTACT_TYPE_CHOICES)
    contact_type_counts = injuries_queryset.values('contact_type').annotate(count=Count('id'))
    contact_type_lookup = {row['contact_type']: row['count'] for row in contact_type_counts}
    contact_type_data = [
        {'label': contact_type_label_map[key], 'count': contact_type_lookup.get(key, 0)}
        for key in ('CONTACT', 'NON_CONTACT', 'OVERUSE')
    ]

    # Total missed games across filtered injuries
    total_missed_games = injuries_queryset.aggregate(s=Sum('missed_games'))['s'] or 0

    # Previous year for YoY chart
    prev_year = selected_year - 1

    # JSON serialization of team comparison for Chart.js
    team_comparison_json = json.dumps(team_comparison)

    context = {
        'monthly_data': json.dumps(monthly_data),
        'monthly_injuries_detail': json.dumps(monthly_injuries_detail),  # Player details for monthly chart
        'injury_type_data': json.dumps(list(injury_type_data)),
        'injury_type_details': json.dumps(injury_type_details),  # Player details for injury type chart
        'body_part_data': json.dumps(list(body_part_data)),
        'body_part_details': json.dumps(body_part_details),  # Player details for body part chart
        'severity_data': json.dumps(list(severity_data)),
        'avg_recovery_time': avg_recovery_time,
        'team_comparison': team_comparison,
        'selected_year': selected_year,
        'date_from': date_from,
        'date_to': date_to,
        'selected_team': team_filter,
        'teams': Team.objects.all() if request.user.role == 'ADMIN' else None,
        'available_years': available_years,
        # Statistics showing ALL injuries are included
        'total_injuries': total_injuries,
        'active_count': active_count,
        'recovering_count': recovering_count,
        'recovered_count': recovered_count,
        'chronic_count': chronic_count,
        'status_breakdown': status_breakdown,
        # Detailed injury list with player information
        'all_injuries_detail': all_injuries_detail,
        'active_injuries_detail': active_injuries_detail,
        'recovered_injuries_detail': recovered_injuries_detail,
        # New context for analytics_new.html
        'contact_type_data': contact_type_data,
        'body_part_counts_json': json.dumps(body_part_counts),
        'team_comparison_json': team_comparison_json,
        'total_missed_games': total_missed_games,
        'prev_year': prev_year,
        'contact_type': contact_type_filter,
        'status': status_filter,
    }
    
    return render(request, 'injury_tracking/analytics.html', context)

# API Views for AJAX
@login_required
def get_player_injuries(request, player_id):
    """Get player's injury history for AJAX requests"""
    if request.user.role not in ['ADMIN', 'COACH', 'DOCTOR']:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    player = get_object_or_404(CustomUser, id=player_id, role='PLAYER')
    
    # Check permissions
    if request.user.role == 'COACH' and request.user.team != player.team:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    injuries = InjuryRecord.objects.filter(player=player).select_related(
        'injury_type', 'severity'
    ).order_by('-injury_date')
    
    data = []
    for injury in injuries:
        data.append({
            'id': injury.id,
            'injury_type': injury.injury_type.name,
            'body_part': injury.body_part.name,
            'severity': injury.severity.name,
            'status': injury.status,
            'injury_date': injury.injury_date.strftime('%Y-%m-%d'),
            'description': injury.description,
            'color_code': injury.severity.color_code,
        })
    
    return JsonResponse({'injuries': data})

@login_required
def update_injury_status(request, injury_id):
    """Update injury status via AJAX"""
    if request.user.role not in ['ADMIN', 'DOCTOR']:
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    injury = get_object_or_404(InjuryRecord, id=injury_id)
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(InjuryRecord.STATUS_CHOICES):
            injury.status = new_status
            
            # When marking as recovered, automatically set medical clearance
            if new_status == 'RECOVERED':
                injury.medical_clearance = True
                if not injury.clearance_date:
                    injury.clearance_date = timezone.now().date()
                
                # Calculate actual recovery time if not set
                if not injury.actual_recovery_time:
                    recovery_days = (timezone.now().date() - injury.injury_date).days
                    if recovery_days > 0:
                        injury.actual_recovery_time = recovery_days
            
            injury.save()
            return JsonResponse({'success': True, 'status': new_status})
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def mark_as_recovered(request, injury_id):
    """Mark injury as recovered with medical clearance"""
    if request.user.role not in ['ADMIN', 'DOCTOR']:
        messages.error(request, "Access denied. Doctor privileges required.")
        return redirect('tracking:injury_list')
    
    injury = get_object_or_404(InjuryRecord, id=injury_id)
    
    if request.method == 'POST':
        injury.status = 'RECOVERED'
        injury.medical_clearance = True
        injury.clearance_date = timezone.now().date()
        
        # Calculate actual recovery time if not set
        if not injury.actual_recovery_time:
            recovery_days = (timezone.now().date() - injury.injury_date).days
            if recovery_days > 0:
                injury.actual_recovery_time = recovery_days
        
        injury.save()
        messages.success(request, f'Injury for {injury.player.get_full_name()} has been marked as recovered with medical clearance.')
        return redirect('tracking:injury_detail', pk=injury.id)
    
    return redirect('tracking:injury_detail', pk=injury.id)

@login_required
def delete_injury(request, injury_id):
    """Delete an injury record (doctors and admins only)"""
    if request.user.role not in ['ADMIN', 'DOCTOR']:
        messages.error(request, "Access denied. Doctor privileges required.")
        return redirect('tracking:injury_list')
    
    injury = get_object_or_404(InjuryRecord, id=injury_id)
    player_name = injury.player.get_full_name()
    
    if request.method == 'POST':
        injury.delete()
        messages.success(request, f'Injury record for {player_name} has been deleted.')
        return redirect('tracking:injury_list')
    
    # GET request - show confirmation page
    context = {
        'injury': injury,
    }
    return render(request, 'injury_tracking/injury_confirm_delete.html', context)