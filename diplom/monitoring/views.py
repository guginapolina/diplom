import datetime
import random
from django.http import JsonResponse
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from .models import Profile, SupportTicket, Device, Specialist, AppointmentSlot, ClientDevice
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import user_passes_test


def is_admin(user):
    return user.is_superuser


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def simulate_telemetry_view(request):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Доступ запрещен'}, status=403)

    # Берем только активных пользователей
    profiles = Profile.objects.filter(is_approved=True, user__is_active=True)
    devices = ClientDevice.objects.filter(user__is_active=True)
    new_tickets = 0
    logs = []

    def process_device(user, dev_type, sn, obj):
        nonlocal new_tickets, logs
        val = 0
        is_critical = False

        # Генерация чисел
        if dev_type == 'thermostat':
            val = round(random.uniform(8.0, 35.0), 1)
            if val < 10 or val > 30:
                is_critical = True
            unit = "°C"
        else:
            val = round(random.uniform(80, 320))
            if val < 100 or val > 300:
                is_critical = True
            unit = "ед."

        # Сохранение в память
        obj.last_metric = val
        obj.last_metric_time = timezone.now()
        obj.save()

        log_time = timezone.localtime(timezone.now()).strftime('%H:%M:%S')

        # Если значение критическое
        if is_critical:
            ticket_title = f"⚠️ АВТО-ТРЕВОГА S/N: {sn}"

            # ЗАЩИТА ОТ СПАМА: Проверяем, есть ли уже активная заявка по этому устройству
            ticket_exists = SupportTicket.objects.filter(user=user, title=ticket_title,
                                                         status__in=['new', 'in_progress']).exists()

            if not ticket_exists:
                # Заявки нет -> Создаем новую!
                SupportTicket.objects.create(
                    user=user,
                    title=ticket_title,
                    description=f"Система телеметрии зафиксировала критическое отклонение!\nПоказатель: {val} {unit}",
                    status='new'
                )
                new_tickets += 1
                logs.append(
                    f"[{log_time}] {obj.get_device_type_display()} (S/N: {sn}) — {val} {unit} | 🔴 СОЗДАНА ЗАЯВКА")
            else:
                # Заявка уже есть -> Просто пишем в лог, что авария продолжается
                logs.append(
                    f"[{log_time}] {obj.get_device_type_display()} (S/N: {sn}) — {val} {unit} | 🟡 Сбой (Заявка уже в очереди)")
        else:
            # Значение в норме
            logs.append(f"[{log_time}] {obj.get_device_type_display()} (S/N: {sn}) — {val} {unit} | 🟢 Норма")

    for p in profiles:
        process_device(p.user, p.device_type, p.serial_number, p)
    for d in devices:
        process_device(d.user, d.device_type, d.serial_number, d)

    return JsonResponse({'status': 'ok', 'new_tickets': new_tickets, 'logs': logs})

@login_required
@user_passes_test(is_admin, login_url='/')
def admin_dashboard_view(request):
    if request.method == "POST":
        if 'approve_id' in request.POST:
            profile_id = request.POST.get('approve_id')
            profile_to_approve = Profile.objects.get(id=profile_id)

            if not Device.objects.filter(serial_number=profile_to_approve.serial_number).exists():
                messages.error(request,
                               f"Ошибка: Устройство {profile_to_approve.serial_number} не найдено на складе! Активация отменена.")
            else:
                profile_to_approve.is_approved = True
                profile_to_approve.save()
                profile_to_approve.user.is_active = True
                profile_to_approve.user.save()
                messages.success(request, f"Пользователь {profile_to_approve.fio} активирован!")

            return redirect('admin_dashboard')

        # === МЯГКОЕ УДАЛЕНИЕ (В АРХИВ) ===
        elif 'archive_id' in request.POST:
            user_id = request.POST.get('archive_id')
            user_to_archive = User.objects.get(id=user_id)
            if user_to_archive.is_superuser:
                messages.error(request, "Нельзя перенести администратора в архив!")
            else:
                user_to_archive.is_active = False  # Выключаем аккаунт
                user_to_archive.save()
                messages.success(request, f"Клиент {user_to_archive.profile.fio} перенесен в архив.")
            return redirect('admin_dashboard')

        # === ВОССТАНОВЛЕНИЕ ИЗ АРХИВА ===
        elif 'restore_id' in request.POST:
            user_id = request.POST.get('restore_id')
            user_to_restore = User.objects.get(id=user_id)
            user_to_restore.is_active = True  # Включаем аккаунт обратно
            user_to_restore.save()
            messages.success(request, f"Клиент {user_to_restore.profile.fio} успешно восстановлен!")
            return redirect('admin_dashboard')

        elif 'create_device' in request.POST:
            new_sn = request.POST.get('new_sn')
            new_model = request.POST.get('new_model')
            if Device.objects.filter(serial_number=new_sn).exists():
                messages.error(request, f"ОШИБКА: S/N {new_sn} уже есть на складе!")
            else:
                Device.objects.create(serial_number=new_sn, model_name=new_model)
                messages.success(request, f"Устройство {new_sn} добавлено.")
            return redirect('admin_dashboard')

        elif 'add_specialist' in request.POST:
            fio = request.POST.get('fio')
            phone = request.POST.get('phone')
            Specialist.objects.create(fio=fio, phone=phone)
            messages.success(request, f"Специалист {fio} успешно добавлен!")
            return redirect('admin_dashboard')

        elif 'delete_specialist' in request.POST:
            sp_id = request.POST.get('specialist_id')
            sp = Specialist.objects.get(id=sp_id)
            sp_fio = sp.fio
            sp.delete()
            messages.success(request, f"Специалист {sp_fio} удален.")
            return redirect('admin_dashboard')

        elif 'add_schedule' in request.POST:
            sp_id = request.POST.get('specialist_id')
            date_str = request.POST.get('date')
            start_str = request.POST.get('start_time')
            end_str = request.POST.get('end_time')

            specialist = Specialist.objects.get(id=sp_id)
            start_dt = datetime.datetime.strptime(f"{date_str} {start_str}", "%Y-%m-%d %H:%M")
            end_dt = datetime.datetime.strptime(f"{date_str} {end_str}", "%Y-%m-%d %H:%M")

            current_dt = start_dt
            slots_count = 0
            while current_dt + datetime.timedelta(hours=2) <= end_dt:
                AppointmentSlot.objects.create(specialist=specialist, date=current_dt.date(), time=current_dt.time())
                current_dt += datetime.timedelta(hours=2)
                slots_count += 1

            messages.success(request, f"График назначен! Создано {slots_count} слотов.")
            return redirect('admin_dashboard')

        elif 'delete_slot' in request.POST:
            slot_id = request.POST.get('slot_id')
            try:
                slot = AppointmentSlot.objects.get(id=slot_id)
                if slot.is_booked:
                    messages.error(request, f"Ошибка: Нельзя удалить слот, он уже занят клиентом!")
                else:
                    slot.delete()
                    messages.success(request, f"Свободный слот успешно удален.")
            except AppointmentSlot.DoesNotExist:
                messages.error(request, "Ошибка: слот не найден.")
            return redirect('admin_dashboard')

        elif 'resolve_phone' in request.POST:
            ticket_id = request.POST.get('ticket_id')
            ticket = SupportTicket.objects.get(id=ticket_id)
            ticket.status = 'resolved'
            ticket.save()
            AppointmentSlot.objects.filter(ticket=ticket).update(is_booked=False, ticket=None)
            messages.success(request, f"Заявка #{ticket.id} закрыта (решено по телефону).")
            return redirect('admin_dashboard')

        elif 'assign_master' in request.POST:
            ticket_id = request.POST.get('ticket_id')
            slot_id = request.POST.get('slot_id')
            ticket = SupportTicket.objects.get(id=ticket_id)
            new_slot = AppointmentSlot.objects.get(id=slot_id)

            AppointmentSlot.objects.filter(ticket=ticket).update(is_booked=False, ticket=None)
            new_slot.is_booked = True
            new_slot.ticket = ticket
            new_slot.save()

            ticket.status = 'in_progress'
            ticket.save()
            messages.success(request, f"Мастер {new_slot.specialist.fio} назначен на заявку #{ticket.id}.")
            return redirect('admin_dashboard')

        elif 'resolve_master' in request.POST:
            ticket_id = request.POST.get('ticket_id')
            ticket = SupportTicket.objects.get(id=ticket_id)
            ticket.status = 'resolved'
            ticket.save()
            AppointmentSlot.objects.filter(ticket=ticket).delete()
            messages.success(request, f"Заявка #{ticket.id} успешно закрыта. Выезд завершен.")
            return redirect('admin_dashboard')

    now = timezone.now()
    expiration_limit = now - datetime.timedelta(days=5)
    expired_users = User.objects.filter(profile__is_approved=False, date_joined__lte=expiration_limit)
    if expired_users.exists():
        expired_users.delete()

    # Считаем активных
    total_users = Profile.objects.filter(is_approved=True, user__is_active=True).count()
    pending_approvals = Profile.objects.filter(is_approved=False).count()
    active_tickets = SupportTicket.objects.filter(status='new').count()

    new_registrations = Profile.objects.filter(is_approved=False).order_by('-id')
    for reg in new_registrations:
        reg.sn_match = Device.objects.filter(serial_number=reg.serial_number).exists()
        expire_at = reg.user.date_joined + datetime.timedelta(days=5)
        time_left = expire_at - now
        if time_left.total_seconds() > 0:
            reg.days_left = time_left.days
            reg.hours_left = time_left.seconds // 3600
            reg.minutes_left = (time_left.seconds % 3600) // 60
        else:
            reg.days_left = reg.hours_left = reg.minutes_left = 0

    # ВЫВОДИМ ВСЕХ (и активных, и архивных), чтобы админ видел архивных и мог восстановить
    all_profiles = Profile.objects.filter(is_approved=True).order_by('fio')

    all_tickets = SupportTicket.objects.all().order_by('-created_at')
    all_devices = Device.objects.all().order_by('-id')
    all_specialists = Specialist.objects.all().order_by('fio')

    context = {
        'total_users': total_users, 'pending_count': pending_approvals, 'active_tickets': active_tickets,
        'new_registrations': new_registrations, 'all_profiles': all_profiles, 'all_tickets': all_tickets,
        'all_devices': all_devices, 'all_specialists': all_specialists,
    }
    return render(request, 'admin_dashboard.html', context)


@login_required
@user_passes_test(is_admin, login_url='/')
def user_history_view(request, user_id):
    client_user = get_object_or_404(User, id=user_id)
    client_profile = get_object_or_404(Profile, user=client_user)

    if request.method == 'POST':
        ticket_id = request.POST.get('ticket_id')
        new_status = request.POST.get('new_status')
        if ticket_id and new_status:
            ticket = SupportTicket.objects.get(id=ticket_id)
            ticket.status = new_status
            ticket.save()
            messages.success(request, f"Статус заявки #{ticket.id} успешно изменен!")
            return redirect('user_history', user_id=user_id)

    client_tickets = SupportTicket.objects.filter(user=client_user).order_by('-created_at')
    return render(request, 'user_history.html', {'client': client_profile, 'tickets': client_tickets})


@login_required(login_url='/')
def dashboard_view(request):
    if request.user.is_superuser:
        return redirect('admin_dashboard')

    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        messages.error(request, "Профиль оборудования не найден.")
        return redirect('login')

    if not profile.is_approved:
        return render(request, 'not_approved.html')

    if request.method == 'POST':
        if 'add_client_device' in request.POST:
            new_sn = request.POST.get('new_sn')
            new_type = request.POST.get('new_type')

            if not Device.objects.filter(serial_number=new_sn).exists():
                messages.error(request, f"Устройство с S/N {new_sn} не найдено в официальной базе склада!")
            elif Profile.objects.filter(serial_number=new_sn).exists() or ClientDevice.objects.filter(
                    serial_number=new_sn).exists():
                messages.error(request, f"Ошибка: Устройство {new_sn} уже зарегистрировано в системе!")
            else:
                ClientDevice.objects.create(user=request.user, device_type=new_type, serial_number=new_sn)
                messages.success(request, f"Устройство {new_sn} успешно добавлено в ваш аккаунт!")
            return redirect('dashboard')

        else:
            title = request.POST.get('title')
            description = request.POST.get('description')
            SupportTicket.objects.create(user=request.user, title=title, description=description)
            messages.success(request, "Заявка в техподдержку успешно отправлена!")
            return redirect('dashboard')

    user_tickets = SupportTicket.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'dashboard.html', {'profile': profile, 'tickets': user_tickets})


def auth_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'register':
            data = request.POST
            sn = data.get('serial_number')
            phone = data.get('phone')

            if Profile.objects.filter(phone=phone).exists():
                messages.error(request, "Этот номер телефона уже зарегистрирован в системе!")
                return render(request, 'index.html', {'register_data': data})

            if User.objects.filter(username=data.get('username')).exists():
                messages.error(request, "Этот логин уже занят! Выберите другой.")
                return render(request, 'index.html', {'register_data': data})

            if Profile.objects.filter(serial_number=sn).exists() or ClientDevice.objects.filter(
                    serial_number=sn).exists():
                messages.error(request,
                               f"Ошибка: Уникальный номер (S/N) '{sn}' совпадает с чьим-то другим оборудованием!")
                return render(request, 'index.html', {'register_data': data})

            new_user = User.objects.create_user(username=data.get('username'), password=data.get('password'))
            new_user.is_active = False
            new_user.save()

            Profile.objects.create(
                user=new_user, fio=data.get('fio'), phone=phone,
                device_type=data.get('device_type'), serial_number=sn, is_approved=False
            )
            messages.success(request, "Регистрация успешна! Ожидайте активации в течении 5 рабочих дней.")
            return redirect('login')

        elif action == 'login':
            u = request.POST.get('login_username')
            p = request.POST.get('login_password')

            # === ПРОВЕРКА АРХИВНОГО АККАУНТА ПЕРЕД ВХОДОМ ===
            try:
                user_check = User.objects.get(username=u)
                if user_check.check_password(p) and not user_check.is_active and not user_check.is_superuser:
                    messages.error(request, "Ваш аккаунт перенесен в архив. Доступ закрыт.")
                    return redirect('login')
            except User.DoesNotExist:
                pass  # Пропускаем, дальше сработает стандартная проверка

            user = authenticate(request, username=u, password=p)

            if user is not None:
                login(request, user)
                if user.is_superuser:
                    return redirect('admin_dashboard')
                else:
                    return redirect('dashboard')
            else:
                messages.error(request, "Неверный логин или пароль.")
                return redirect('login')

    return render(request, 'index.html')