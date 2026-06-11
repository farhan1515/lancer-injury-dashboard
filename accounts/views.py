from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from .forms import (
    BasicRegistrationForm, PlayerProfileForm, CoachProfileForm, DoctorProfileForm,
    TeamSelectionForm, CoachTeamSelectionForm, UserProfileForm, TeamPermissionRequestForm,
    PlayerRegisterStep1Form, PlayerRegisterStep2Form,
    PlayerSelfPersonalForm, PlayerSelfSportForm,
)
from .models import PlayerProfile, CoachProfile, DoctorProfile, TeamPermissionRequest, TeamPermission, CustomUser

def csrf_failure(request, reason=""):
    """Friendly CSRF failure handler.

    Most CSRF 403s on this app come from stale tokens after a session rotation
    (login, registration step transition, server restart). Instead of showing
    Django's debug 403 page, drop a flash message and bounce the user back to
    the same URL so they get a fresh form + token.
    """
    from django.contrib import messages as _messages
    _messages.warning(
        request,
        "Your session timed out — please try again."
    )
    target = request.META.get('HTTP_REFERER') or request.path or '/login/'
    # Don't loop on a POST URL — fall back to login
    if request.method == 'POST' and target == request.path:
        target = '/login/'
    return redirect(target)


SESSION_KEY_REG_STEP1 = 'player_register_step1'


def _infer_role_from_email(email):
    """Mirror BasicRegistrationForm.get_role_from_email() without a full form."""
    email = (email or '').lower()
    from .models import EmailRoleMapping
    for mapping in EmailRoleMapping.objects.filter(is_active=True):
        if mapping.email_pattern.startswith('@'):
            if email.endswith(mapping.email_pattern):
                return mapping.role, mapping.team
        elif email == mapping.email_pattern.lower():
            return mapping.role, mapping.team
    if email.endswith('@athlete.uwindsor.ca'):
        return 'PLAYER', None
    if email.endswith('@coach.uwindsor.ca'):
        return 'COACH', None
    if email.endswith('@doctor.uwindsor.ca'):
        return 'DOCTOR', None
    return 'PLAYER', None


def register_view(request):
    """Step 1 of registration. For PLAYER role, redirects to step 2; for COACH/DOCTOR,
    creates the account and sends them to login + the existing complete-registration flow.
    """
    if request.method == 'POST':
        form = PlayerRegisterStep1Form(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            role, team = _infer_role_from_email(cd['email'])

            # Stash step-1 data in session; commit happens in step 2 (for players)
            # or right here (for coach/doctor — no extra step in this slice).
            request.session[SESSION_KEY_REG_STEP1] = {
                'first_name': cd['first_name'],
                'last_name': cd['last_name'],
                'email': cd['email'],
                'student_id': cd['student_id'],
                'phone': cd.get('phone', ''),
                'password': cd['password1'],
                'role': role,
                'team_id': team.id if team else None,
            }
            # Hold the uploaded photo in session as base64-ish? Simpler: write it to
            # the user on commit. We re-prompt on step 2 if it's a player, since we
            # can't easily round-trip a file through a session.
            if role == 'PLAYER':
                # Persist whether they attached a photo so step 2 can re-prompt only if needed.
                request.session[SESSION_KEY_REG_STEP1]['has_photo'] = bool(cd.get('profile_picture'))
                # Save photo immediately to /tmp via the user-doesn't-exist-yet workaround:
                # We instead defer the photo to step 2's POST (player re-uploads only if they
                # cleared the file). To keep UX minimal, we store the file in the session-keyed
                # cache by saving it to a pending PlayerProfile-less location:
                photo = cd.get('profile_picture')
                if photo:
                    # Save under MEDIA_ROOT/_pending_profile/<sessionkey>.<ext>
                    from django.core.files.storage import default_storage
                    from django.core.files.base import ContentFile
                    ext = (photo.name.rsplit('.', 1)[-1] or 'jpg').lower()
                    if not request.session.session_key:
                        request.session.save()
                    pending_path = f"_pending_profile/{request.session.session_key}.{ext}"
                    if default_storage.exists(pending_path):
                        default_storage.delete(pending_path)
                    default_storage.save(pending_path, ContentFile(photo.read()))
                    request.session[SESSION_KEY_REG_STEP1]['pending_photo_path'] = pending_path
                return redirect('player_register_step2')

            # COACH / DOCTOR path: create the user now, send them to login.
            user = _create_user_from_step1(request.session[SESSION_KEY_REG_STEP1])
            request.session.pop(SESSION_KEY_REG_STEP1, None)
            messages.success(request, 'Account created. Please log in to complete your registration.')
            return redirect('login')
    else:
        form = PlayerRegisterStep1Form()
    return render(request, 'accounts/register.html', {
        'form': form,
        'step': 1,
        'total_steps': 2,
    })


def _create_user_from_step1(data, profile_picture_file=None, pending_photo_path=None):
    """Create CustomUser from session-stored step 1 data."""
    from django.core.files.storage import default_storage
    from django.contrib.auth.hashers import make_password
    email = data['email']
    username = email.split('@')[0]
    # Ensure uniqueness of username
    base, n = username, 1
    while CustomUser.objects.filter(username=username).exists():
        n += 1
        username = f"{base}{n}"
    team = None
    if data.get('team_id'):
        from .models import Team
        team = Team.objects.filter(id=data['team_id']).first()
    user = CustomUser(
        username=username,
        email=email,
        first_name=data['first_name'],
        last_name=data['last_name'],
        role=data['role'],
        team=team,
        phone=data.get('phone', ''),
        is_registration_complete=False,
    )
    user.password = make_password(data['password'])
    # Attach photo: either fresh from form (preferred), or pending file from step 1.
    if profile_picture_file:
        user.profile_picture = profile_picture_file
    elif pending_photo_path and default_storage.exists(pending_photo_path):
        from django.core.files.base import ContentFile
        with default_storage.open(pending_photo_path, 'rb') as f:
            user.profile_picture.save(pending_photo_path.split('/')[-1], ContentFile(f.read()), save=False)
        default_storage.delete(pending_photo_path)
    user.save()
    return user


def player_register_step2_view(request):
    """Step 2 of player registration: Sports & Team info, then auto-login + dashboard."""
    step1 = request.session.get(SESSION_KEY_REG_STEP1)
    if not step1 or step1.get('role') != 'PLAYER':
        messages.error(request, 'Please start registration from the beginning.')
        return redirect('register')

    if request.method == 'POST':
        form = PlayerRegisterStep2Form(request.POST)
        if form.is_valid():
            # Create the user now
            user = _create_user_from_step1(
                step1,
                profile_picture_file=None,
                pending_photo_path=step1.get('pending_photo_path'),
            )
            user.team = form.cleaned_data['team']
            user.is_registration_complete = True
            # store student_id on the PlayerProfile
            profile = form.save(commit=False)
            profile.user = user
            profile.student_id = step1.get('student_id', '')
            profile.save()
            user.save()
            request.session.pop(SESSION_KEY_REG_STEP1, None)
            # Auto-login and redirect straight to the player dashboard
            login(request, user)
            messages.success(request, 'Welcome! Your account is ready.')
            return redirect('tracking:player_dashboard')
    else:
        form = PlayerRegisterStep2Form()
    return render(request, 'accounts/register_step2.html', {
        'form': form,
        'step': 2,
        'total_steps': 2,
        'first_name': step1.get('first_name', ''),
    })

@login_required
def complete_registration_view(request):
    """Complete registration with role-specific information"""
    user = request.user
    
    if user.is_registration_complete:
        return redirect('dashboard')
    
    if request.method == 'POST':
        if user.role == 'PLAYER':
            profile_form = PlayerProfileForm(request.POST, request.FILES)
            team_form = TeamSelectionForm(request.POST)
            
            if profile_form.is_valid() and team_form.is_valid():
                # Create player profile
                profile = profile_form.save(commit=False)
                profile.user = user
                profile.save()
                
                # Assign team
                user.team = team_form.cleaned_data['team']
                user.is_registration_complete = True
                user.save()
                
                messages.success(request, 'Registration completed successfully!')
                return redirect('dashboard')
                
        elif user.role == 'COACH':
            profile_form = CoachProfileForm(request.POST)
            
            if profile_form.is_valid():
                # Create coach profile
                profile = profile_form.save(commit=False)
                profile.user = user
                profile.save()
                
                # Coaches cannot select their own team - only admins can assign teams
                # If user already has a team from EmailRoleMapping, keep it
                # Otherwise, leave it blank for admin assignment (security measure)
                
                user.is_registration_complete = True
                user.save()
                
                if not user.team:
                    messages.success(request, 'Registration completed! An admin will assign your team shortly.')
                else:
                    messages.success(request, 'Registration completed successfully!')
                return redirect('dashboard')
                
        elif user.role == 'DOCTOR':
            profile_form = DoctorProfileForm(request.POST)
            
            if profile_form.is_valid():
                # Create doctor profile
                profile = profile_form.save(commit=False)
                profile.user = user
                profile.save()
                
                # Doctors don't need team assignment
                user.is_registration_complete = True
                user.save()
                
                messages.success(request, 'Registration completed successfully!')
                return redirect('dashboard')
    else:
        # Initialize forms based on user role
        if user.role == 'PLAYER':
            profile_form = PlayerProfileForm()
            team_form = TeamSelectionForm()
        elif user.role == 'COACH':
            profile_form = CoachProfileForm()
            # Coaches cannot select their own team - only admins can assign (security)
            team_form = None
        elif user.role == 'DOCTOR':
            profile_form = DoctorProfileForm()
            team_form = None
        else:
            messages.error(request, 'Invalid user role.')
            return redirect('register')
    
    context = {
        'user': user,
        'profile_form': profile_form,
        'team_form': team_form,
    }
    
    return render(request, 'accounts/complete_registration.html', context)

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            # Check if user needs to complete registration
            if not user.is_registration_complete:
                return redirect('complete_registration')
            return redirect('dashboard')
        else:
            return render(request, 'accounts/login.html', {'error': 'Invalid credentials'})
    return render(request, 'accounts/login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

@login_required
def dashboard(request):
    """Redirect to appropriate dashboard based on user role"""
    user = request.user
    
    # Check if registration is complete first
    if not user.is_registration_complete:
        return redirect('complete_registration')
    
    if user.role == 'ADMIN':
        return redirect('tracking:admin_dashboard')
    elif user.role == 'COACH':
        # If coach has no team, show a message instead of redirecting to coach_dashboard
        if not user.team:
            messages.info(request, 'Your registration is complete! An administrator will assign your team shortly.')
            # Show a simple page or redirect to profile
            return redirect('profile')
        return redirect('tracking:coach_dashboard')
    elif user.role == 'DOCTOR':
        return redirect('tracking:doctor_dashboard')
    elif user.role == 'PLAYER':
        return redirect('tracking:player_dashboard')
    else:
        return redirect('login')

@login_required
def profile_view(request):
    user = request.user

    # Players get a streamlined profile page showing only fields captured at registration.
    if user.role == 'PLAYER':
        return _player_profile_view(request)

    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            # Security: Prevent coaches from changing their team assignment
            # Team can only be changed by admins via admin panel
            if user.role == 'COACH' and 'team' in request.POST:
                messages.warning(request, 'Team assignment cannot be changed. Please contact an administrator.')
                return redirect('profile')
            
            form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('profile')
    else:
        form = UserProfileForm(instance=user)
    
    # Get role-specific profile information
    role_profile = None
    if user.role == 'PLAYER':
        try:
            role_profile = user.playerprofile
        except PlayerProfile.DoesNotExist:
            role_profile = None
    elif user.role == 'COACH':
        try:
            role_profile = user.coachprofile
        except CoachProfile.DoesNotExist:
            role_profile = None
    elif user.role == 'DOCTOR':
        try:
            role_profile = user.doctorprofile
        except DoctorProfile.DoesNotExist:
            role_profile = None
    
    context = {
        'form': form,
        'user': user,
        'role_profile': role_profile,
    }
    
    return render(request, 'accounts/user_profile.html', context)

def _player_profile_view(request):
    """Player-only profile page. Shows only fields collected during registration."""
    user = request.user
    profile, _ = PlayerProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        personal = PlayerSelfPersonalForm(request.POST, request.FILES, instance=user)
        sport = PlayerSelfSportForm(request.POST, instance=profile)
        # Pre-fill team since it lives on CustomUser, not PlayerProfile
        if user.team and 'team' not in request.POST:
            sport.fields['team'].initial = user.team
        if personal.is_valid() and sport.is_valid():
            personal.save()
            profile = sport.save(commit=False)
            profile.user = user
            profile.save()
            user.team = sport.cleaned_data['team']
            user.save(update_fields=['team'])
            messages.success(request, 'Profile updated.')
            return redirect('profile')
    else:
        personal = PlayerSelfPersonalForm(instance=user)
        sport = PlayerSelfSportForm(instance=profile, initial={'team': user.team})

    return render(request, 'accounts/player_profile.html', {
        'user': user,
        'profile': profile,
        'personal_form': personal,
        'sport_form': sport,
    })


@login_required
def player_calendar(request):
    """Full monthly calendar for the player — team events, appointments, and injuries."""
    if request.user.role != 'PLAYER':
        messages.error(request, "Player access required.")
        return redirect('dashboard')

    from datetime import timedelta
    import json
    from injury_tracking.models import Event, Appointment, InjuryRecord

    today = timezone.now().date()
    cutoff = today - timedelta(days=60)

    team_events = []
    if request.user.team:
        team_events = list(Event.objects.filter(
            team=request.user.team,
            end_datetime__date__gte=cutoff,
        ).order_by('start_datetime'))

    player_appointments = list(Appointment.objects.filter(
        player=request.user,
        preferred_date__gte=cutoff,
    ).select_related('therapist').order_by('preferred_date'))

    player_injuries = list(InjuryRecord.objects.filter(
        player=request.user,
        injury_date__gte=cutoff,
    ).select_related('injury_type', 'body_part').order_by('-injury_date'))

    events_data = []
    for ev in team_events:
        events_data.append({
            'title': ev.title,
            'start': ev.start_datetime.isoformat(),
            'end': ev.end_datetime.isoformat(),
            'color': '#0b76ef',
            'extendedProps': {
                'kind': 'team_event',
                'event_type': ev.get_event_type_display(),
                'location': ev.location or '',
            },
        })
    for a in player_appointments:
        color = '#10b981' if a.status == 'CONFIRMED' else (
            '#ef4444' if a.status == 'CANCELLED' else '#f59e0b'
        )
        events_data.append({
            'title': f"Appointment ({a.get_status_display()})",
            'start': a.preferred_date.isoformat(),
            'allDay': True,
            'color': color,
            'extendedProps': {
                'kind': 'appointment',
                'status': a.get_status_display(),
                'therapist': (a.therapist.get_full_name() if a.therapist else 'TBD'),
                'time_slot': a.get_preferred_time_slot_display(),
                'note': a.note or '',
            },
        })
    for inj in player_injuries:
        events_data.append({
            'title': f"{inj.injury_type.name} — {inj.body_part.name}",
            'start': inj.injury_date.isoformat(),
            'allDay': True,
            'color': '#ef4444',
            'extendedProps': {
                'kind': 'injury',
                'injury_type': inj.injury_type.name,
                'body_part': inj.body_part.name,
                'status': inj.get_status_display(),
            },
        })

    # Upcoming events for the desktop right sidebar
    upcoming = []
    for ev in team_events:
        if ev.start_datetime.date() >= today:
            upcoming.append({
                'when': ev.start_datetime,
                'title': ev.title,
                'kind': 'event',
                'meta': ev.get_event_type_display(),
            })
    for a in player_appointments:
        if a.preferred_date >= today:
            upcoming.append({
                'when': a.preferred_date,
                'title': f"Appointment — {a.get_status_display()}",
                'kind': 'appointment',
                'meta': a.get_preferred_time_slot_display(),
            })
    # Sort by datetime/date — coerce date to datetime for comparison
    from datetime import datetime as _dt
    def _key(item):
        w = item['when']
        return w if isinstance(w, _dt) else _dt.combine(w, _dt.min.time())
    upcoming.sort(key=_key)
    upcoming = upcoming[:6]

    unread_notifications = 0
    try:
        from .models import Notification
        unread_notifications = Notification.objects.filter(
            user=request.user, is_read=False
        ).count()
    except Exception:
        pass

    return render(request, 'accounts/player_calendar.html', {
        'events_json': json.dumps(events_data),
        'upcoming': upcoming,
        'unread_notifications': unread_notifications,
    })


@login_required
def get_notifications(request):
    """JSON: last 10 notifications + unread count, for the bell dropdown."""
    from .models import Notification
    qs = Notification.objects.filter(user=request.user).order_by('-created_at')
    unread_count = qs.filter(is_read=False).count()
    items = []
    for n in qs[:10]:
        items.append({
            'id': n.id,
            'message': n.message,
            'type': n.notification_type,
            'link': n.link or '',
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat(),
        })
    return JsonResponse({'unread_count': unread_count, 'notifications': items})


@login_required
@require_POST
def mark_notification_read(request, pk):
    from .models import Notification
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=['is_read'])
    return JsonResponse({'ok': True})


@login_required
@require_POST
def mark_all_notifications_read(request):
    from .models import Notification
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'ok': True})


@login_required
def request_team_access(request):
    if request.user.role not in ['COACH', 'DOCTOR', 'ADMIN']:
        messages.error(request, 'Only coaches and doctors can request additional team access.')
        return redirect('dashboard')
    if request.method == 'POST':
        form = TeamPermissionRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req.user = request.user
            req.status = 'PENDING'
            req.save()
            messages.success(request, 'Your request has been submitted for admin approval.')
            return redirect('request_team_access')
    else:
        form = TeamPermissionRequestForm()
    my_requests = TeamPermissionRequest.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'accounts/request_team_access.html', {'form': form, 'my_requests': my_requests})

@login_required
def admin_review_requests(request):
    if request.user.role != 'ADMIN':
        messages.error(request, 'Admin access required.')
        return redirect('dashboard')
    pending = TeamPermissionRequest.objects.filter(status='PENDING')
    return render(request, 'accounts/admin_team_requests.html', {'pending': pending})

@login_required
def admin_decide_request(request, req_id, decision):
    if request.user.role != 'ADMIN':
        messages.error(request, 'Admin access required.')
        return redirect('dashboard')
    req = get_object_or_404(TeamPermissionRequest, id=req_id)
    if req.status != 'PENDING':
        messages.info(request, 'This request has already been processed.')
        return redirect('admin_review_requests')
    if decision not in ['approve', 'deny']:
        messages.error(request, 'Invalid decision.')
        return redirect('admin_review_requests')
    if decision == 'approve':
        # Create TeamPermission
        TeamPermission.objects.get_or_create(user=req.user, team=req.team, role_scope=req.role_scope)
        req.status = 'APPROVED'
        messages.success(request, 'Request approved and access granted.')
    else:
        req.status = 'DENIED'
        messages.info(request, 'Request denied.')
    req.reviewed_by = request.user
    req.reviewed_at = timezone.now()
    req.save()
    return redirect('admin_review_requests')
