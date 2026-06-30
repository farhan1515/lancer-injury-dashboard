from django.urls import path
from . import views

app_name = 'injury_tracking'

urlpatterns = [
    # Dashboard views
    path('', views.dashboard, name='dashboard'),
    path('admin/', views.admin_dashboard, name='admin_dashboard'),
    path('coach/', views.coach_dashboard, name='coach_dashboard'),
    path('doctor/', views.doctor_dashboard, name='doctor_dashboard'),
    path('player/', views.player_dashboard, name='player_dashboard'),
    
    # Injury management
    path('injuries/', views.InjuryListView.as_view(), name='injury_list'),
    path('injuries/<int:pk>/', views.InjuryDetailView.as_view(), name='injury_detail'),
    path('injuries/create/', views.InjuryCreateView.as_view(), name='injury_create'),
    path('injuries/<int:pk>/update/', views.InjuryUpdateView.as_view(), name='injury_update'),
    
    # Analytics
    path('analytics/', views.analytics_dashboard, name='analytics'),

    # Player self-service flows
    path('player/report-injury/', views.player_report_injury, name='player_report_injury'),
    path('player/report-injury/submit/', views.player_report_injury_submit, name='player_report_injury_submit'),
    path('player/request-appointment/', views.player_request_appointment_submit, name='player_request_appointment_submit'),

    # Doctor / Coach inboxes
    path('pending-reviews/', views.pending_review_inbox, name='pending_review_inbox'),
    path('appointments/inbox/', views.appointment_inbox, name='appointment_inbox'),
    path('appointments/<int:pk>/<str:decision>/', views.appointment_decide, name='appointment_decide'),
    
    # API endpoints
    path('api/player/<int:player_id>/injuries/', views.get_player_injuries, name='player_injuries_api'),
    path('api/injury/<int:injury_id>/status/', views.update_injury_status, name='update_injury_status'),
    
    # Injury actions
    path('injuries/<int:injury_id>/recover/', views.mark_as_recovered, name='mark_as_recovered'),
    path('injuries/<int:injury_id>/delete/', views.delete_injury, name='delete_injury'),

    # Events (Coach Calendar)
    path('events/', views.events_calendar, name='events_calendar'),
    path('events/create/', views.event_create, name='event_create'),
    path('events/<int:pk>/', views.event_detail, name='event_detail'),
    path('events/feed/', views.events_feed, name='events_feed'),
]
