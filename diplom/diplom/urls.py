from django.contrib import admin
from django.urls import path
from monitoring import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.auth_view, name='login'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('management/', views.admin_dashboard_view, name='admin_dashboard'),

    path('logout/', views.logout_view, name='logout'),
    path('management/user/<int:user_id>/', views.user_history_view, name='user_history'),

    path('simulate-telemetry/', views.simulate_telemetry_view, name='simulate_telemetry'),
]