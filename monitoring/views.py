import datetime
import random
import json
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


# ==========================================
# АВТОМАТИЧЕСКАЯ ГЕНЕРАЦИЯ ТЕСТОВЫХ КЛИЕНТОВ
# ==========================================
def _ensure_test_users():
    Device.objects.get_or_create(serial_number='ZN-HOT', defaults={'model_name': 'ZONT H-1V'})
    Device.objects.get_or_create(serial_number='ZN-COLD', defaults={'model_name': 'ZONT H-1V'})

    if not User.objects.filter(username='test_hot').exists():
        u1 = User.objects.create_user(username='test_hot', password='123')
        u1.is_active = True
        u1.save()
        Profile.objects.create(
            user=u1, fio='Тестов Тест Тестович', phone='+7 (000) 000-00-01',
            device_type='thermostat', serial_number='ZN-HOT', is_approved=True,
            target_temp=50.0
        )

    if not User.objects.filter(username='test_cold').exists():
        u2 = User.objects.create_user(username='test_cold', password='123')
        u2.is_active = True
        u2.save()
        Profile.objects.create(
            user=u2, fio='Тестова Теста Тестовна', phone='+7 (000) 000-00-02',
            device_type='thermostat', serial_number='ZN-COLD', is_approved=True,
            target_temp=45.0
        )


# ==========================================
# ЯДРО ТЕЛЕМЕТРИИ С РАСЧЕТОМ ОТКЛОНЕНИЙ
# ==========================================
def generate_telemetry_for_device(user, dev_type, sn, obj):
    target = getattr(obj, 'target_temp', 50.0)
    
    val = 0
    is_critical = False
    alarm_reason = ""

    if dev_type == 'thermostat':
        # 1. Искусственные сбои ТОЛЬКО для тестовых стендов ZN-HOT и ZN-COLD
        if sn == 'ZN-HOT':
            if random.random() < 0.8:
                val = round(random.uniform(61.0, 75.0), 1) # Искусственный перегрев > 60
            else:
                val = round(random.uniform(target - 1.0, target + 1.0), 1)
                
        elif sn == 'ZN-COLD':
            if random.random() < 0.8:
                val = round(random.uniform(20.0, 39.0), 1) # Искусственное падение < 40
            else:
                val = round(random.uniform(target - 1.0, target + 1.0), 1)
                
        else:
            # 2. Обычные пользователи: рандомная телеметрия
            # Цифры "прыгают" вокруг целевой температуры для реалистичности
            jump_range = 3.0 
            val = round(random.uniform(target - jump_range, target + jump_range), 1)
            
            # Жёстко ограничиваем телеметрию в рамках [40.0; 60.0], 
            # чтобы у обычных юзеров никогда не создавались случайные автотревоги
            val = max(40.0, min(val, 60.0))

        unit = "°C"
        
        # 3. Логика автотревоги: срабатывает строго если t < 40 или t > 60
        if val < 40.0:
            is_critical = True
            alarm_reason = f"Температура упала ниже 40 {unit} (текущая: {val} {unit})"
        elif val > 60.0:
            is_critical = True
            alarm_reason = f"Перегрев котла выше 60 {unit} (текущая: {val} {unit})"

   
    if hasattr(obj, 'save'):
        obj.last_metric = val
        obj.last_metric_time = timezone.now()
        obj.save()

    return val, unit, is_critical, alarm_reason


@login_required
def simulate_telemetry_view(request):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Доступ запрещен'}, status=403)

    profiles = list(Profile.objects.filter(is_approved=True, user__is_active=True))
    devices = list(ClientDevice.objects.filter(user__is_active=True))

    all_equipment = []
    for p in profiles:
        all_equipment.append({'user': p.user, 'type': p.device_type, 'sn': p.serial_number, 'obj': p})
  
    for d in devices:
        all_equipment.append({'user': d.user, 'type': d.device_type, 'sn': d.serial_number, 'obj': d})

    new_tickets = 0
    logs = []

    if all_equipment:
        target_equip = random.choice(all_equipment)
        user = target_equip['user']
        sn = target_equip['sn']
        obj = target_equip['obj']

        log_time = timezone.localtime(timezone.now()).strftime('%H:%M:%S')

        val, unit, is_critical, alarm_reason = generate_telemetry_for_device(user, target_equip['type'], sn, obj)

        if is_critical:
            ticket_title = f"⚠️ АВТО-ТРЕВОГА S/N: {sn}"
            ticket_exists = SupportTicket.objects.filter(user=user, title=ticket_title, status__in=['new', 'in_progress']).exists()

            if not ticket_exists:
                SupportTicket.objects.create(
                    user=user,
                    title=ticket_title,
                    description=f"Внимание, сбой телеметрии: {alarm_reason}!\nПоказатель: {val} {unit}\nЗаданная цель: {obj.target_temp} {unit}",
                    status='new'
                )
                new_tickets += 1
                logs.append(f"[{log_time}] {obj.get_device_type_display()} (S/N: {sn}) — {val} {unit} | 🔴 {alarm_reason.upper()}! ЗАЯВКА СОЗДАНА")
            else:
                logs.append(f"[{log_time}] {obj.get_device_type_display()} (S/N: {sn}) — {val} {unit} | 🟡 Авария продолжается (в очереди)")
        else:
            logs.append(f"[{log_time}] {obj.get_device_type_display()} (S/N: {sn}) — {val} {unit} | 🟢 Норма")

    return JsonResponse({'status': 'ok', 'new_tickets': new_tickets, 'logs': logs})


@login_required
def user_simulate_telemetry_view(request):
    if request.user.is_superuser:
        return JsonResponse({'error': 'Админам сюда не нужно'}, status=403)

    try:
        profile = Profile.objects.get(user=request.user)
    except Profile.DoesNotExist:
        return JsonResponse({'error': 'Профиль не найден'}, status=404)

    if not profile.is_approved:
        return JsonResponse({'error': 'Аккаунт не активирован'}, status=403)

    all_equipment = [(request.user, profile.device_type, profile.serial_number, profile)]
    for d in request.user.additional_devices.all():
        all_equipment.append((request.user, d.device_type, d.serial_number, d))

    new_tickets = 0
    logs = []

    if all_equipment:
        target_equip = random.choice(all_equipment)
        user, dev_type, sn, obj = target_equip

        val, unit, is_critical, alarm_reason = generate_telemetry_for_device(user, dev_type, sn, obj)
        log_time = timezone.localtime(timezone.now()).strftime('%H:%M:%S')

        if is_critical:
            ticket_title = f"⚠️ АВТО-ТРЕВОГА S/N: {sn}"
            ticket_exists = SupportTicket.objects.filter(user=user, title=ticket_title, status__in=['new', 'in_progress']).exists()

            if not ticket_exists:
                SupportTicket.objects.create(
                    user=user,
                    title=ticket_title,
                    description=f"Внимание, сбой телеметрии: {alarm_reason}!\nПоказатель: {val} {unit}\nЗаданная цель: {obj.target_temp} {unit}",
                    status='new'
                )
                new_tickets += 1
                logs.append(f"[{log_time}] {obj.get_device_type_display()} (S/N: {sn}) — {val} {unit} | 🔴 СБОЙ: {alarm_reason}! Ожидайте мастера")
            else:
                logs.append(f"[{log_time}] {obj.get_device_type_display()} (S/N: {sn}) — {val} {unit} | 🟡 Ремонт в процессе")
        else:
            logs.append(f"[{log_time}] {obj.get_device_type_display()} (S/N: {sn}) — {val} {unit} | 🟢 Устройство в норме")

    return JsonResponse({'status': 'ok', 'new_tickets': new_tickets, 'logs': logs})


@login_required
@user_passes_test(is_admin, login_url='/')
def admin_dashboard_view(request):
    _ensure_test_users()

    if request.method == "POST":
        if 'archive_id' in request.POST:
            user_id = request.POST.get('archive_id')
            user_to_archive = User.objects.get(id=user_id)
            if user_to_archive.is_superuser:
                messages.error(request, "Нельзя перенести администратора в архив!")
            else:
                user_to_archive.is_active = False
                user_to_archive.save()
                messages.success(request, f"Клиент {user_to_archive.profile.fio} перенесен в архив.")
            return redirect('admin_dashboard')

        elif 'restore_id' in request.POST:
            user_id = request.POST.get('restore_id')
            user_to_restore = User.objects.get(id=user_id)
            user_to_restore.is_active = True
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

    total_users = Profile.objects.filter(is_approved=True, user__is_active=True).count()
    all_profiles = Profile.objects.filter(is_approved=True).order_by('fio')
    all_tickets = SupportTicket.objects.all().order_by('-created_at')

    auto_tickets = all_tickets.filter(title__startswith='⚠️ АВТО-ТРЕВОГА')
    manual_tickets = all_tickets.exclude(title__startswith='⚠️ АВТО-ТРЕВОГА')

    auto_tickets_new = auto_tickets.filter(status='new').count()
    manual_tickets_new = manual_tickets.filter(status='new').count()
    tickets_in_progress = all_tickets.filter(status='in_progress').count()
    tickets_resolved = all_tickets.filter(status='resolved').count()
    active_tickets = all_tickets.filter(status='new').count()

    # ПОДГОТОВКА ДАННЫХ ДЛЯ ЛИНЕЙНОГО ГРАФИКА ЗА 7 ДНЕЙ
    now = timezone.now()
    last_7_days = [now - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    
    chart_labels = [d.strftime('%d.%m') for d in last_7_days]
    auto_counts = [0] * 7
    manual_counts = [0] * 7

    for idx, d in enumerate(last_7_days):
        start_of_day = d.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + datetime.timedelta(days=1)
        
        auto_counts[idx] = auto_tickets.filter(created_at__gte=start_of_day, created_at__lt=end_of_day).count()
        manual_counts[idx] = manual_tickets.filter(created_at__gte=start_of_day, created_at__lt=end_of_day).count()

    all_devices = Device.objects.all().order_by('-id')
    all_specialists = Specialist.objects.all().order_by('fio')

    context = {
        'total_users': total_users,
        'active_tickets': active_tickets,
        'auto_tickets_new': auto_tickets_new,
        'manual_tickets_new': manual_tickets_new,
        'tickets_in_progress': tickets_in_progress,
        'tickets_resolved': tickets_resolved,
        
        # Данные для графиков (JSON format for JS)
        'chart_labels': json.dumps(chart_labels),
        'chart_auto_data': json.dumps(auto_counts),
        'chart_manual_data': json.dumps(manual_counts),

        'all_profiles': all_profiles,
        'all_tickets': all_tickets,
        'auto_tickets': auto_tickets,
        'manual_tickets': manual_tickets,
        'all_devices': all_devices,
        'all_specialists': all_specialists,
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
        if 'update_limits' in request.POST:
            sn = request.POST.get('device_sn')
            target_t = float(request.POST.get('target_temp', 50.0))

            if profile.serial_number == sn:
                profile.target_temp = target_t
                profile.save()
            else:
                try:
                    dev = ClientDevice.objects.get(user=request.user, serial_number=sn)
                    dev.target_temp = target_t
                    dev.save()
                except ClientDevice.DoesNotExist:
                    pass
            messages.success(request, f"Целевая температура для {sn} успешно задана!")
            return redirect('dashboard')

        elif 'add_client_device' in request.POST:
            new_sn = request.POST.get('new_sn')
            new_type = request.POST.get('new_type')

            if not Device.objects.filter(serial_number=new_sn).exists():
                messages.error(request, f"Устройство с S/N {new_sn} не найдено в базе!")
            elif Profile.objects.filter(serial_number=new_sn).exists() or ClientDevice.objects.filter(
                    serial_number=new_sn).exists():
                messages.error(request, f"Ошибка: Устройство {new_sn} уже занято!")
            else:
                ClientDevice.objects.create(user=request.user, device_type=new_type, serial_number=new_sn)
                messages.success(request, f"Устройство {new_sn} добавлено!")
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

            # 1. ЖЕСТКАЯ ПРОВЕРКА: ЕСТЬ ЛИ СЕРИЙНИК НА СКЛАДЕ? (Изменен текст ошибки)
            if not Device.objects.filter(serial_number=sn).exists():
                messages.error(request, "Ошибка: Серийный номер не найден. Пожалуйста, проверьте серийный номер на вашем устройстве и введите его снова.")
                return render(request, 'index.html', {'register_data': data})

            # 2. ПРОВЕРКА НА УНИКАЛЬНОСТЬ ТЕЛЕФОНА
            if Profile.objects.filter(phone=phone).exists():
                messages.error(request, "Этот телефон уже зарегистрирован!")
                return render(request, 'index.html', {'register_data': data})

            # 3. ПРОВЕРКА ЛОГИНА
            if User.objects.filter(username=data.get('username')).exists():
                messages.error(request, "Логин занят! Выберите другой.")
                return render(request, 'index.html', {'register_data': data})

            # 4. ПРОВЕРКА: НЕ ЗАНЯЛ ЛИ ЭТОТ S/N УЖЕ ДРУГОЙ КЛИЕНТ?
            if Profile.objects.filter(serial_number=sn).exists() or ClientDevice.objects.filter(serial_number=sn).exists():
                messages.error(request, f"Ошибка: S/N '{sn}' уже используется другим клиентом!")
                return render(request, 'index.html', {'register_data': data})

            # ЕСЛИ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ — СОЗДАЕМ И СРАЗУ АКТИВИРУЕМ
            new_user = User.objects.create_user(username=data.get('username'), password=data.get('password'))
            new_user.is_active = True  # <--- Сразу активен
            new_user.save()

            Profile.objects.create(
                user=new_user, fio=data.get('fio'), phone=phone,
                device_type=data.get('device_type'), serial_number=sn, 
                is_approved=True,  # <--- Сразу подтвержден (ручная активация больше не нужна)
                target_temp=50.0
            )
            
            # Сообщение об успешной и моментальной регистрации
            messages.success(request, "Регистрация успешна! Устройство найдено, аккаунт автоматически активирован. Вы можете войти.")
            return redirect('login')

        elif action == 'login':
            u = request.POST.get('login_username')
            p = request.POST.get('login_password')

            try:
                user_check = User.objects.get(username=u)
                if user_check.check_password(p) and not user_check.is_active and not user_check.is_superuser:
                    messages.error(request, "Доступ к вашему аккаунту закрыт.")
                    return redirect('login')
            except User.DoesNotExist:
                pass

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