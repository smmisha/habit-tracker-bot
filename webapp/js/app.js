// Инициализация Telegram WebApp SDK
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand(); // Разворачиваем на весь экран
    tg.ready();
}

// Извлекаем user_id
function getUserId() {
    if (tg?.initDataUnsafe?.user?.id) {
        return tg.initDataUnsafe.user.id;
    }
    const urlParams = new URLSearchParams(window.location.search);
    const paramId = urlParams.get('user_id');
    if (paramId) {
        return paramId;
    }
    return '5037862619'; // Резервный ID для тестирования
}

const userId = getUserId();
let relapseSource = 'direct'; // 'direct' или 'panic'

// Уведомления (Toast)
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = '✅';
    if (type === 'error') icon = '❌';
    if (type === 'info') icon = 'ℹ️';
    
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideDown 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) reverse';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Переключение вкладок (Tabs Routing)
function switchTab(tabId) {
    // Скрываем все вкладки
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    // Убираем активный класс у кнопок
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    
    // Показываем целевую вкладку
    const targetTab = document.getElementById(`tab-${tabId}`);
    if (targetTab) {
        targetTab.classList.add('active');
    }
    
    // Делаем кнопку меню активной
    const targetBtn = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
    if (targetBtn) {
        targetBtn.classList.add('active');
    }
    
    // Обновляем заголовки
    const headerTitle = document.getElementById('header-title');
    if (tabId === 'dashboard') {
        headerTitle.textContent = 'DASHBOARD';
    } else if (tabId === 'journal') {
        headerTitle.textContent = 'ДНЕВНИК';
    } else if (tabId === 'sos') {
        headerTitle.textContent = 'HELP / SOS';
    }
}

// Слушатели для Bottom Nav
document.querySelectorAll('.nav-item').forEach(button => {
    button.addEventListener('click', () => {
        const tabId = button.getAttribute('data-tab');
        switchTab(tabId);
    });
});

// Проверяем GET-параметр tab для автоматического перехода
function checkDefaultTab() {
    const urlParams = new URLSearchParams(window.location.search);
    const tabParam = urlParams.get('tab');
    if (tabParam && ['dashboard', 'journal', 'sos'].includes(tabParam)) {
        switchTab(tabParam);
    } else {
        switchTab('dashboard');
    }
}

// Загрузка всей статистики и данных с бэкенда
async function loadAllData() {
    try {
        const response = await fetch(`/api/stats?user_id=${userId}`);
        if (!response.ok) {
            throw new Error(`Ошибка: ${response.status}`);
        }
        
        const data = await response.json();
        
        // 1. Сводка заголовка
        document.getElementById('header-subtitle').textContent = `Ваш стрик чистоты: ${data.streak_str || '0 дней'}`;
        
        // 2. Рендер дашборда
        renderStats(data);
        renderCalendar(data.calendar_days);
        renderChart(data.triggers);
        
        // 2.5. Рендер цитаты
        if (data.quote) {
            document.getElementById('daily-quote').textContent = data.quote;
        }
        
        // 3. Рендер истории дневника
        renderJournalHistory(data.journal_history);
        
    } catch (error) {
        console.error('Ошибка загрузки данных:', error);
        showToast('Не удалось загрузить данные с сервера', 'error');
        document.getElementById('header-subtitle').textContent = 'Ошибка подключения к серверу';
    }
}

// Отображение карточек статистики
function renderStats(data) {
    document.getElementById('current-streak').textContent = data.streak_str || '0 дн.';
    document.getElementById('total-relapses').textContent = data.total_relapses ?? '0';
}

// Рендеринг календаря
function renderCalendar(days) {
    const grid = document.getElementById('calendar-grid');
    grid.innerHTML = '';
    
    if (!days || days.length === 0) {
        grid.innerHTML = '<div style="grid-column: span 7; text-align: center; color: var(--text-secondary);">Нет данных за 30 дней</div>';
        return;
    }
    
    days.forEach(day => {
        const dayEl = document.createElement('div');
        dayEl.className = 'calendar-day';
        
        const dateObj = new Date(day.date);
        const dayNumber = dateObj.getDate();
        dayEl.innerHTML = `<span>${dayNumber}</span>`;
        
        if (day.status === 'clean') {
            dayEl.classList.add('day-clean');
        } else if (day.status === 'relapsed') {
            dayEl.classList.add('day-relapse');
            if (day.relapse_count > 1) {
                const subLabel = document.createElement('span');
                subLabel.className = 'day-label-sub';
                subLabel.innerHTML = `x${day.relapse_count}`;
                dayEl.appendChild(subLabel);
            }
        } else {
            dayEl.classList.add('day-no-data');
        }
        
        const formattedDate = dateObj.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
        let tooltipText = `${formattedDate}: `;
        if (day.status === 'clean') tooltipText += 'Чистый день! 💪';
        else if (day.status === 'relapsed') tooltipText += `Срывов: ${day.relapse_count} ⚠️`;
        else tooltipText += 'Нет отметки 💤';
        
        dayEl.title = tooltipText;
        grid.appendChild(dayEl);
    });
}

// Рендеринг графика триггеров
let triggersChart = null;
function renderChart(triggers) {
    const canvas = document.getElementById('triggers-chart');
    const noDataMsg = document.getElementById('no-chart-data');
    
    const labels = Object.keys(triggers || {});
    const values = Object.values(triggers || {});
    const totalTriggers = values.reduce((sum, val) => sum + val, 0);
    
    if (totalTriggers === 0) {
        canvas.classList.add('hidden');
        noDataMsg.classList.remove('hidden');
        return;
    }
    
    canvas.classList.remove('hidden');
    noDataMsg.classList.add('hidden');
    
    if (triggersChart) {
        triggersChart.destroy();
    }
    
    const ctx = canvas.getContext('2d');
    triggersChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: ['#ff3b30', '#ff9500', '#af52de', '#5856d6', '#007aff', '#34c759'],
                borderWidth: 1,
                borderColor: 'rgba(255, 255, 255, 0.1)'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#85899e',
                        font: { family: 'Outfit', size: 11 },
                        padding: 12
                    }
                }
            },
            cutout: '72%'
        }
    });
}

// Отображение истории дневника
function renderJournalHistory(history) {
    const container = document.getElementById('journal-history');
    container.innerHTML = '';
    
    if (!history || history.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: var(--text-secondary); font-size: 13px;">Записей пока нет. Самое время начать!</p>';
        return;
    }
    
    history.forEach(item => {
        const card = document.createElement('div');
        card.className = 'journal-card';
        
        const dateObj = new Date(item.date);
        const formattedDate = dateObj.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
        
        card.innerHTML = `
            <div class="journal-date">📅 ${formattedDate}</div>
            <div class="journal-content">${item.content}</div>
        `;
        container.appendChild(card);
    });
}

// --- СОХРАНЕНИЕ ДНЕВНИКА ---
document.getElementById('btn-save-journal').addEventListener('click', async () => {
    const btn = document.getElementById('btn-save-journal');
    const input = document.getElementById('journal-input');
    const text = input.value.trim();
    
    if (text.length < 5) {
        showToast('Заметка слишком короткая (минимум 5 символов)', 'error');
        return;
    }
    
    btn.disabled = true;
    btn.querySelector('.spinner').classList.remove('hidden');
    btn.querySelector('.btn-text').textContent = 'Сохранение...';
    
    try {
        const response = await fetch('/api/journal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, content: text })
        });
        
        const resData = await response.json();
        if (response.ok && resData.success) {
            showToast(resData.message);
            input.value = ''; // очищаем поле ввода
            await loadAllData(); // перезагружаем историю
        } else {
            showToast(resData.error || 'Ошибка сохранения заметки', 'error');
        }
    } catch (err) {
        console.error(err);
        showToast('Ошибка сети при сохранении', 'error');
    } finally {
        btn.disabled = false;
        btn.querySelector('.spinner').classList.add('hidden');
        btn.querySelector('.btn-text').textContent = 'Сохранить запись';
    }
});

// --- SOS И СРЫВ ЛОГИКА ---

// 0. Запуск динамического ИИ-SOS
document.getElementById('btn-start-sos').addEventListener('click', async () => {
    const btn = document.getElementById('btn-start-sos');
    const startScreen = document.getElementById('sos-start-screen');
    const dynamicContent = document.getElementById('sos-dynamic-content');
    const listContainer = document.getElementById('sos-guidelines-list');
    
    btn.disabled = true;
    btn.querySelector('.spinner').classList.remove('hidden');
    btn.querySelector('.btn-text').textContent = 'Подключение ИИ-ассистента...';
    
    try {
        const response = await fetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, action: 'start' })
        });
        const resData = await response.json();
        
        if (response.ok && resData.success && resData.guidelines) {
            // Отрисовываем шаги
            listContainer.innerHTML = '';
            resData.guidelines.forEach((step, idx) => {
                const card = document.createElement('div');
                card.className = 'guideline-card glass';
                card.style.display = 'flex';
                card.style.gap = '16px';
                card.style.alignItems = 'center';
                
                card.innerHTML = `
                    <span class="num">${idx + 1}</span>
                    <div class="text">
                        <h3>${step.title}</h3>
                        <p>${step.description}</p>
                    </div>
                `;
                listContainer.appendChild(card);
            });
            
            // Переключаем экраны
            startScreen.classList.add('hidden');
            dynamicContent.classList.remove('hidden');
            showToast('Индивидуальные шаги сгенерированы!');
        } else {
            showToast(resData.error || 'Ошибка при загрузке SOS-шагов', 'error');
        }
    } catch (err) {
        console.error(err);
        showToast('Ошибка сети при запуске SOS', 'error');
    } finally {
        btn.disabled = false;
        btn.querySelector('.spinner').classList.add('hidden');
        btn.querySelector('.btn-text').textContent = '🆘 Мне тяжело / Нужна помощь';
    }
});

// 1. SOS - Справился (Helped)
document.getElementById('btn-panic-helped').addEventListener('click', async () => {
    const btn = document.getElementById('btn-panic-helped');
    btn.disabled = true;
    
    try {
        const response = await fetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, action: 'helped' })
        });
        const resData = await response.json();
        if (response.ok && resData.success) {
            showToast(resData.message || 'Отлично! Уведомление отправлено в чат.');
            // Сбрасываем экран SOS
            document.getElementById('sos-dynamic-content').classList.add('hidden');
            document.getElementById('sos-start-screen').classList.remove('hidden');
            switchTab('dashboard');
        } else {
            showToast(resData.error || 'Ошибка при сохранении статуса', 'error');
        }
    } catch (err) {
        console.error(err);
        showToast('Ошибка соединения', 'error');
    } finally {
        btn.disabled = false;
    }
});

// 2. SOS - Не справился (Failed)
document.getElementById('btn-panic-failed').addEventListener('click', () => {
    relapseSource = 'panic';
    // Скрываем карточки рекомендаций и показываем форму срыва
    document.getElementById('sos-guidelines-box').classList.add('hidden');
    document.getElementById('relapse-form').classList.remove('hidden');
    showToast('Пожалуйста, укажите триггер срыва', 'info');
});

// 3. Прямая кнопка срыва
document.getElementById('btn-show-relapse-form').addEventListener('click', () => {
    relapseSource = 'direct';
    document.getElementById('relapse-form').classList.remove('hidden');
});

// 4. Отмена срыва (скрыть форму)
document.getElementById('btn-cancel-relapse').addEventListener('click', () => {
    document.getElementById('relapse-form').classList.add('hidden');
    document.getElementById('sos-guidelines-box').classList.remove('hidden');
});

// 5. Обработка селекта причин (вывод текстового поля для "Другое")
document.getElementById('relapse-trigger').addEventListener('change', (e) => {
    const val = e.target.value;
    const otherGroup = document.getElementById('other-trigger-group');
    if (val === 'Другое') {
        otherGroup.classList.remove('hidden');
    } else {
        otherGroup.classList.add('hidden');
    }
});

// 6. Подтверждение и отправка срыва
document.getElementById('btn-submit-relapse').addEventListener('click', async () => {
    const btn = document.getElementById('btn-submit-relapse');
    const triggerSelect = document.getElementById('relapse-trigger');
    const otherInput = document.getElementById('other-trigger-input');
    
    let triggerValue = triggerSelect.value;
    if (triggerValue === 'Другое') {
        const text = otherInput.value.trim();
        if (text.length < 3) {
            showToast('Пожалуйста, опишите причину подробнее', 'error');
            return;
        }
        triggerValue = `Другое: ${text}`;
    }
    
    btn.disabled = true;
    btn.textContent = 'Обработка...';
    
    try {
        let endpoint = '/api/relapse';
        let bodyPayload = { user_id: userId, trigger_reason: triggerValue };
        
        if (relapseSource === 'panic') {
            endpoint = '/api/panic';
            bodyPayload = { user_id: userId, action: 'failed', trigger_reason: triggerValue };
        }
        
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bodyPayload)
        });
        
        const resData = await response.json();
        if (response.ok && resData.success) {
            showToast(resData.message || 'Счетчик сброшен. Пожалуйста, откройте чат бота.');
            
            // Очищаем форму и возвращаем исходное состояние
            document.getElementById('relapse-form').classList.add('hidden');
            document.getElementById('sos-dynamic-content').classList.add('hidden');
            document.getElementById('sos-start-screen').classList.remove('hidden');
            document.getElementById('sos-guidelines-box').classList.remove('hidden');
            otherInput.value = '';
            triggerSelect.value = 'Скука / Безделье';
            document.getElementById('other-trigger-group').classList.add('hidden');
            
            // Перезагружаем данные и выводим дашборд
            await loadAllData();
            switchTab('dashboard');
            
            // По возможности закрываем Mini App, чтобы пользователь сразу зашел в ИИ-чат
            if (tg) {
                setTimeout(() => tg.close(), 1500);
            }
        } else {
            showToast(resData.error || 'Ошибка сохранения срыва', 'error');
        }
    } catch (err) {
        console.error(err);
        showToast('Ошибка сети при отправке срыва', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Подтвердить срыв';
    }
});

// 7. Функция добавления на главный экран (Shortcut)
function initHomeScreenShortcut() {
    if (tg && typeof tg.checkHomeScreenStatus === 'function') {
        try {
            tg.checkHomeScreenStatus(function(status) {
                console.log("Home screen status:", status);
                const container = document.getElementById('add-to-home-container');
                if (container) {
                    if (status === 'missed') {
                        container.classList.remove('hidden');
                    } else {
                        container.classList.add('hidden');
                    }
                }
            });
        } catch (e) {
            console.error("Ошибка проверки статуса домашнего экрана:", e);
        }
    }
    
    const btn = document.getElementById('btn-add-to-home');
    if (btn) {
        btn.addEventListener('click', () => {
            if (tg && typeof tg.addToHomeScreen === 'function') {
                try {
                    tg.addToHomeScreen();
                } catch (e) {
                    console.error("Ошибка при добавлении на главный экран:", e);
                    showToast("Не удалось добавить на главный экран", "error");
                }
            } else {
                showToast("Эта функция не поддерживается вашим устройством", "info");
            }
        });
    }
}

// Запуск при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    checkDefaultTab();
    loadAllData();
    initHomeScreenShortcut();
});
