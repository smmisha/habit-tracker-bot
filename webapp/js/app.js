// Инициализация Telegram WebApp SDK
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand(); // Разворачиваем на весь экран
    tg.ready();
    try {
        if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor('#0b0c10');
        if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor('#0b0c10');
    } catch (e) {
        console.debug('Telegram theme color sync skipped:', e);
    }
}

// Функции тактильного виброотклика (Haptic Feedback)
function hapticImpact(style = 'light') {
    try {
        if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.impactOccurred === 'function') {
            tg.HapticFeedback.impactOccurred(style);
        }
    } catch (e) {
        console.debug('Haptic impact error:', e);
    }
}

function hapticSelection() {
    try {
        if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.selectionChanged === 'function') {
            tg.HapticFeedback.selectionChanged();
        }
    } catch (e) {
        console.debug('Haptic selection error:', e);
    }
}

function hapticNotification(type = 'success') {
    try {
        if (tg && tg.HapticFeedback && typeof tg.HapticFeedback.notificationOccurred === 'function') {
            tg.HapticFeedback.notificationOccurred(type);
        }
    } catch (e) {
        console.debug('Haptic notification error:', e);
    }
}

// Обертка над fetch для автоматической передачи Telegram initData в заголовках
async function apiFetch(url, options = {}) {
    const headers = options.headers ? { ...options.headers } : {};
    if (tg && tg.initData) {
        headers['X-Telegram-Init-Data'] = tg.initData;
    }
    return fetch(url, { ...options, headers });
}

// Навигация и нативная кнопка «Назад» в Telegram
function updateBackButton() {
    if (!tg || !tg.BackButton) return;

    const activeTab = document.querySelector('.tab-content.active')?.id;

    if (activeTab === 'tab-dashboard') {
        tg.BackButton.hide();
    } else {
        tg.BackButton.show();
    }
}

function handleNativeBack() {
    hapticImpact('light');

    const activeTab = document.querySelector('.tab-content.active')?.id;

    // 1. Если открыта вкладка «Дневник» -> возврат на дашборд
    if (activeTab === 'tab-journal') {
        switchTab('dashboard');
        updateBackButton();
        return;
    }

    // 2. Если открыта вкладка «SOS» -> плавный возврат по глубине шагов
    if (activeTab === 'tab-sos') {
        // Форма фиксации срыва
        const relapseForm = document.getElementById('relapse-form');
        if (relapseForm && !relapseForm.classList.contains('hidden')) {
            relapseForm.classList.add('hidden');
            updateBackButton();
            return;
        }

        // Раунд 3: Напарник -> возврат в Раунд 2
        const stepPartner = document.getElementById('spiritual-step-partner');
        if (stepPartner && !stepPartner.classList.contains('hidden')) {
            stepPartner.classList.add('hidden');
            document.getElementById('spiritual-step-round2')?.classList.remove('hidden');
            updateBackButton();
            return;
        }

        // Раунд 2: Углубленное чтение -> возврат в Раунд 1
        const stepRound2 = document.getElementById('spiritual-step-round2');
        if (stepRound2 && !stepRound2.classList.contains('hidden')) {
            stepRound2.classList.add('hidden');
            document.getElementById('spiritual-step-study')?.classList.remove('hidden');
            updateBackButton();
            return;
        }

        // Раунд 1: Изучение статьи -> возврат к выбору темы искушения
        const stepStudy = document.getElementById('spiritual-step-study');
        if (stepStudy && !stepStudy.classList.contains('hidden')) {
            stepStudy.classList.add('hidden');
            document.getElementById('spiritual-step-select')?.classList.remove('hidden');
            updateBackButton();
            return;
        }

        // Блок духовной помощи (выбор темы) -> возврат к базовым советам SOS
        const spiritualContent = document.getElementById('sos-spiritual-content');
        if (spiritualContent && !spiritualContent.classList.contains('hidden')) {
            spiritualContent.classList.add('hidden');
            document.getElementById('panic-relapse-section')?.classList.remove('hidden');
            document.getElementById('sos-dynamic-content')?.classList.remove('hidden');
            updateBackButton();
            return;
        }

        // Базовые советы SOS -> возврат на начальный экран SOS
        const dynamicContent = document.getElementById('sos-dynamic-content');
        if (dynamicContent && !dynamicContent.classList.contains('hidden')) {
            dynamicContent.classList.add('hidden');
            document.getElementById('sos-start-screen')?.classList.remove('hidden');
            updateBackButton();
            return;
        }

        // Начальный экран SOS -> возврат на дашборд
        switchTab('dashboard');
        updateBackButton();
        return;
    }

    // Резервный возврат на дашборд
    switchTab('dashboard');
    updateBackButton();
}

// Регистрируем слушатель нативной кнопки «Назад»
if (tg && tg.BackButton) {
    try {
        tg.BackButton.onClick(handleNativeBack);
    } catch (e) {
        console.debug('BackButton registration error:', e);
    }
}

// Пользователя сервер определяет только по подписанному initData (заголовок ставит apiFetch)
const NO_ACCESS_TEXT = 'Откройте приложение заново через бота в Telegram';

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
        toast.style.transition = 'opacity 0.25s ease, transform 0.25s ease';
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(-12px)';
        setTimeout(() => toast.remove(), 260);
    }, 3000);
}

// Переключение вкладок (Tabs Routing)
function switchTab(tabId) {
    hapticSelection();

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
        notifySosOpened();
    }

    updateBackButton();
}

// Слушатели для Bottom Nav
document.querySelectorAll('.nav-item').forEach(button => {
    button.addEventListener('click', () => {
        const tabId = button.getAttribute('data-tab');
        switchTab(tabId);
    });
});

// Проверяем GET-параметр tab или start_param для автоматического перехода
function checkDefaultTab() {
    let tabParam = null;
    
    // Сначала пробуем получить из initDataUnsafe.start_param (для нативных ссылок t.me/bot/app?startapp=xxx)
    if (tg?.initDataUnsafe?.start_param) {
        tabParam = tg.initDataUnsafe.start_param;
    }
    
    // Если нет, пробуем получить из GET-параметра URL
    if (!tabParam) {
        const urlParams = new URLSearchParams(window.location.search);
        tabParam = urlParams.get('tab');
    }
    
    if (tabParam && ['dashboard', 'journal', 'sos'].includes(tabParam)) {
        switchTab(tabParam);
    } else {
        switchTab('dashboard');
    }
}

// Загрузка всей статистики и данных с бэкенда
async function loadAllData() {
    try {
        // Вне Telegram подписи нет, поэтому запрашивать личные данные незачем
        const response = tg?.initData ? await apiFetch('/api/stats') : null;
        if (!response || response.status === 401) {
            document.getElementById('header-subtitle').textContent = NO_ACCESS_TEXT;
            document.getElementById('daily-quote').textContent = 'Личные данные видны только вам и только из Telegram.';
            showToast(NO_ACCESS_TEXT, 'error');
            return;
        }
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
    
    // Добавляем заголовки дней недели
    const weekdays = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];
    weekdays.forEach(wd => {
        const wdEl = document.createElement('div');
        wdEl.className = 'calendar-weekday-header';
        wdEl.textContent = wd;
        grid.appendChild(wdEl);
    });
    
    // Вычисляем отступ для первого дня, чтобы выровнять по дням недели
    const firstDayDate = new Date(days[0].date);
    const startWeekday = (firstDayDate.getDay() + 6) % 7;
    
    for (let i = 0; i < startWeekday; i++) {
        const emptyEl = document.createElement('div');
        emptyEl.className = 'calendar-day-empty';
        grid.appendChild(emptyEl);
    }
    
    days.forEach(day => {
        const dayEl = document.createElement('div');
        dayEl.className = 'calendar-day';
        
        const dateObj = new Date(day.date);
        const dayNumber = dateObj.getDate();
        dayEl.innerHTML = `<span>${dayNumber}</span>`;
        
        if (day.status === 'clean') {
            if (day.excuse_reason) {
                dayEl.classList.add('day-late');
            } else {
                dayEl.classList.add('day-clean');
            }
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
        if (day.status === 'clean') {
            if (day.excuse_reason) {
                tooltipText += `Чисто (${day.excuse_reason}) ⏰`;
            } else {
                tooltipText += 'Чистый день! 💪';
            }
        }
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
    const chartWrap = canvas?.closest('.chart-container');
    
    const labels = Object.keys(triggers || {});
    const values = Object.values(triggers || {});
    const totalTriggers = values.reduce((sum, val) => sum + val, 0);
    
    if (totalTriggers === 0) {
        canvas.classList.add('hidden');
        noDataMsg.classList.remove('hidden');
        chartWrap?.classList.remove('has-chart');
        return;
    }
    
    canvas.classList.remove('hidden');
    noDataMsg.classList.add('hidden');
    chartWrap?.classList.add('has-chart');
    
    if (triggersChart) {
        triggersChart.destroy();
    }
    
    if (typeof Chart === 'undefined') {
        console.warn('Chart.js is not loaded');
        return;
    }
    const ctx = canvas.getContext('2d');
    triggersChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: values,
                backgroundColor: ['#ff3b30', '#ff9500', '#af52de', '#5856d6', '#007aff', '#34c759'],
                borderWidth: 2,
                borderColor: '#12141c',
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#9296ad',
                        font: { family: 'Outfit', size: 11 },
                        usePointStyle: true,
                        pointStyle: 'circle',
                        boxWidth: 8,
                        padding: 14
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
        
        const dateEl = document.createElement('div');
        dateEl.className = 'journal-date';
        dateEl.textContent = `📅 ${formattedDate}`;

        const contentEl = document.createElement('div');
        contentEl.className = 'journal-content';
        contentEl.textContent = item.content || '';

        card.appendChild(dateEl);
        card.appendChild(contentEl);
        container.appendChild(card);
    });
}

// --- СОХРАНЕНИЕ ДНЕВНИКА ---
document.getElementById('btn-save-journal').addEventListener('click', async () => {
    const btn = document.getElementById('btn-save-journal');
    const input = document.getElementById('journal-input');
    const text = input.value.trim();
    
    if (text.length < 5) {
        hapticNotification('error');
        showToast('Заметка слишком короткая (минимум 5 символов)', 'error');
        return;
    }
    
    btn.disabled = true;
    btn.querySelector('.spinner').classList.remove('hidden');
    btn.querySelector('.btn-text').textContent = 'Сохранение...';
    
    try {
        const response = await apiFetch('/api/journal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: text })
        });
        
        const resData = await response.json();
        if (response.ok && resData.success) {
            hapticNotification('success');
            showToast(resData.message);
            input.value = ''; // очищаем поле ввода
            await loadAllData(); // перезагружаем историю
        } else {
            hapticNotification('error');
            showToast(resData.error || 'Ошибка сохранения заметки', 'error');
        }
    } catch (err) {
        console.error(err);
        hapticNotification('error');
        showToast('Ошибка сети при сохранении', 'error');
    } finally {
        btn.disabled = false;
        btn.querySelector('.spinner').classList.add('hidden');
        btn.querySelector('.btn-text').textContent = 'Сохранить запись';
    }
});

// --- SOS И СРЫВ ЛОГИКА ---

document.getElementById('btn-start-sos').addEventListener('click', () => {
    startSosProcess();
});

// Отметка активности при открытии раздела SOS
async function notifySosOpened() {
    try {
        await apiFetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'initiate' })
        });
    } catch (e) {
        console.error('Ошибка отметки открытия SOS:', e);
    }
}

// Непосредственно сам процесс запуска SOS и получения советов от ИИ
async function startSosProcess() {
    const btn = document.getElementById('btn-start-sos');
    const startScreen = document.getElementById('sos-start-screen');
    const dynamicContent = document.getElementById('sos-dynamic-content');
    const listContainer = document.getElementById('sos-guidelines-list');
    
    btn.disabled = true;
    btn.querySelector('.spinner').classList.remove('hidden');
    btn.querySelector('.btn-text').textContent = 'Подключение ИИ-ассистента...';
    
    try {
        const response = await apiFetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'start' })
        });
        const resData = await response.json();
        
        if (response.ok && resData.success && resData.guidelines) {
            // Отрисовываем шаги
            listContainer.innerHTML = '';
            resData.guidelines.forEach((step, idx) => {
                const card = document.createElement('div');
                card.className = 'guideline-card glass';

                const numEl = document.createElement('span');
                numEl.className = 'num';
                numEl.textContent = String(idx + 1);

                const textEl = document.createElement('div');
                textEl.className = 'text';

                const h3El = document.createElement('h3');
                h3El.textContent = step.title || '';

                const pEl = document.createElement('p');
                pEl.textContent = step.description || '';

                textEl.appendChild(h3El);
                textEl.appendChild(pEl);
                card.appendChild(numEl);
                card.appendChild(textEl);
                listContainer.appendChild(card);
            });
            
            // Переключаем экраны
            startScreen.classList.add('hidden');
            dynamicContent.classList.remove('hidden');
            updateBackButton();
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
}

// 1. SOS - Справился (Helped)
document.getElementById('btn-panic-helped').addEventListener('click', async () => {
    const btn = document.getElementById('btn-panic-helped');
    btn.disabled = true;
    
    try {
        const response = await apiFetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'helped' })
        });
        const resData = await response.json();
        if (response.ok && resData.success) {
            hapticNotification('success');
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

// Переход от базовых SOS-шагов к духовному подкреплению (jw.org)
document.getElementById('btn-panic-failed')?.addEventListener('click', async () => {
    try {
        await apiFetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'failed' })
        });
    } catch (e) {
        console.error(e);
    }
    
    document.getElementById('sos-dynamic-content')?.classList.add('hidden');
    document.getElementById('sos-spiritual-content')?.classList.remove('hidden');
    document.getElementById('spiritual-step-select')?.classList.remove('hidden');
    document.getElementById('spiritual-step-study')?.classList.add('hidden');
    document.getElementById('spiritual-step-round2')?.classList.add('hidden');
    document.getElementById('spiritual-step-partner')?.classList.add('hidden');
    updateBackButton();
    showToast('Переходим к духовному подкреплению (jw.org)...', 'info');
});

// 2. Индивидуальная духовная помощь (wol.jw.org / jw.org)
let selectedTemptationTypes = [];
let currentSpiritualNotes = '';
let cachedPartnerUsername = null;
let currentPrimaryArticleTitle = 'Духовная публикация';
let currentRound2ArticleTitle = 'Углубленный материал';
let round1ReflectionSaved = false;
let round2ReflectionSaved = false;
let round1PromptedReflection = false;
let round2PromptedReflection = false;

async function submitArticleReflection(roundNum) {
    const isRound2 = roundNum === 2;
    const input = document.getElementById(isRound2 ? 'round2-reflection-input' : 'spiritual-reflection-input');
    const feedbackEl = document.getElementById(isRound2 ? 'round2-reflection-feedback' : 'spiritual-reflection-feedback');
    const btn = document.getElementById(isRound2 ? 'btn-save-round2-reflection' : 'btn-save-spiritual-reflection');
    if (!input || !btn) return true;

    const text = input.value.trim();
    const articleTitle = isRound2 ? currentRound2ArticleTitle : currentPrimaryArticleTitle;

    if (text.length < 15) {
        hapticNotification('error');
        if (feedbackEl) {
            feedbackEl.textContent = 'Напиши чуть подробнее: что именно из статьи запомнилось, какие примерно стихи задели и какой вывод ты берёшь для себя.';
            feedbackEl.className = 'reflection-feedback is-warning';
        }
        input.focus();
        return false;
    }

    btn.disabled = true;
    btn.querySelector('.spinner')?.classList.remove('hidden');
    const btnTextEl = btn.querySelector('.btn-text');
    if (btnTextEl) btnTextEl.textContent = 'Сохранение разбора...';

    try {
        const resp = await apiFetch('/api/spiritual_reflection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                article_title: articleTitle,
                reflection_text: text,
                round: roundNum
            })
        });
        const resData = await resp.json();

        if (!resp.ok) {
            hapticNotification('error');
            showToast(resData.error || 'Ошибка сохранения разбора статьи', 'error');
            return false;
        }

        if (!resData.accepted) {
            hapticNotification('error');
            if (feedbackEl) {
                feedbackEl.textContent = resData.feedback || 'Распиши мысль немного подробнее и искреннее.';
                feedbackEl.className = 'reflection-feedback is-warning';
            }
            input.focus();
            return false;
        }

        hapticNotification('success');
        if (feedbackEl) {
            feedbackEl.textContent = resData.feedback || 'Вывод сохранён в дневник.';
            feedbackEl.className = 'reflection-feedback is-success';
        }
        if (isRound2) {
            round2ReflectionSaved = true;
        } else {
            round1ReflectionSaved = true;
        }
        showToast('Разбор статьи сохранён в дневник', 'success');
        await loadAllData();
        return true;
    } catch (e) {
        console.error('Reflection submit error:', e);
        hapticNotification('error');
        showToast('Ошибка сети при сохранении вывода', 'error');
        return false;
    } finally {
        btn.disabled = false;
        btn.querySelector('.spinner')?.classList.add('hidden');
        if (btnTextEl) btnTextEl.textContent = '💾 Сохранить вывод и стихи';
    }
}

document.getElementById('btn-save-spiritual-reflection')?.addEventListener('click', () => {
    submitArticleReflection(1);
});

document.getElementById('btn-save-round2-reflection')?.addEventListener('click', () => {
    submitArticleReflection(2);
});

// Обработка чипов искушений (мультивыбор)
document.querySelectorAll('#temptation-chips-container .chip-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        hapticSelection();
        const currentType = btn.getAttribute('data-type');
        if (btn.classList.contains('active')) {
            btn.classList.remove('active');
            selectedTemptationTypes = selectedTemptationTypes.filter(t => t !== currentType);
        } else {
            btn.classList.add('active');
            if (!selectedTemptationTypes.includes(currentType)) {
                selectedTemptationTypes.push(currentType);
            }
        }
    });
});

// Кнопка подбора духовного решения
document.getElementById('btn-find-spiritual-solution')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-find-spiritual-solution');
    currentSpiritualNotes = document.getElementById('spiritual-user-notes')?.value || '';
    
    btn.disabled = true;
    btn.querySelector('.spinner')?.classList.remove('hidden');
    btn.querySelector('.btn-text').textContent = 'Подбираем материалы...';
    
    await loadSpiritualSolution(selectedTemptationTypes, currentSpiritualNotes);
    
    btn.disabled = false;
    btn.querySelector('.spinner')?.classList.add('hidden');
    btn.querySelector('.btn-text').textContent = '🔍 Получить духовное решение';
});

// Кнопка смены темы / возврата к выбору
document.getElementById('btn-spiritual-change-topic')?.addEventListener('click', () => {
    document.getElementById('spiritual-step-study')?.classList.add('hidden');
    document.getElementById('spiritual-step-round2')?.classList.add('hidden');
    document.getElementById('spiritual-step-partner')?.classList.add('hidden');
    document.getElementById('spiritual-step-select')?.classList.remove('hidden');
    updateBackButton();
});

// Раунд 1: Кнопка «Помогло! Тяга отступила»
document.getElementById('btn-spiritual-helped')?.addEventListener('click', async () => {
    const reflInput = document.getElementById('spiritual-reflection-input');
    const reflText = (reflInput?.value || '').trim();
    if (!round1ReflectionSaved) {
        if (reflText.length > 0) {
            const ok = await submitArticleReflection(1);
            if (!ok) return;
        } else if (!round1PromptedReflection) {
            round1PromptedReflection = true;
            reflInput?.focus();
            showToast('После прочтения запиши, что запомнил и какие стихи (или нажми ещё раз)', 'info');
            return;
        }
    }

    try {
        await apiFetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'helped' })
        });
    } catch (e) {
        console.error(e);
    }
    hapticNotification('success');
    showToast('Слава Богу! Вы устояли и защитили свой стрик! 💪', 'success');
    document.getElementById('sos-spiritual-content')?.classList.add('hidden');
    document.getElementById('panic-relapse-section')?.classList.remove('hidden');
    document.getElementById('sos-start-screen')?.classList.remove('hidden');
    switchTab('dashboard');
});

// Раунд 1: Кнопка перехода к Раунду 2
document.getElementById('btn-spiritual-to-round2')?.addEventListener('click', async () => {
    document.getElementById('spiritual-step-study')?.classList.add('hidden');
    document.getElementById('spiritual-step-round2')?.classList.remove('hidden');
    updateBackButton();
    showToast('Загружаем углубленный материал Раунда 2...', 'info');
    await loadRound2Solution(selectedTemptationTypes, currentSpiritualNotes);
});

// Раунд 2: Кнопка «Помогло! Тяга отступила»
document.getElementById('btn-round2-helped')?.addEventListener('click', async () => {
    const reflInput = document.getElementById('round2-reflection-input');
    const reflText = (reflInput?.value || '').trim();
    if (!round2ReflectionSaved) {
        if (reflText.length > 0) {
            const ok = await submitArticleReflection(2);
            if (!ok) return;
        } else if (!round2PromptedReflection) {
            round2PromptedReflection = true;
            reflInput?.focus();
            showToast('Напиши коротко после чтения, что запомнилось и какие стихи (или нажми ещё раз)', 'info');
            return;
        }
    }

    try {
        await apiFetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'helped' })
        });
    } catch (e) {
        console.error(e);
    }
    hapticNotification('success');
    showToast('Слава Богу! Раунд 2 помог успокоить сердце, стрик защищен! 💪', 'success');
    document.getElementById('sos-spiritual-content')?.classList.add('hidden');
    document.getElementById('panic-relapse-section')?.classList.remove('hidden');
    document.getElementById('sos-start-screen')?.classList.remove('hidden');
    switchTab('dashboard');
});

// Раунд 2: Кнопка перехода к Раунду 3 («Не помогло — Раунд 3: Написать напарнику лично»)
document.getElementById('btn-round2-to-partner')?.addEventListener('click', () => {
    document.getElementById('spiritual-step-round2')?.classList.add('hidden');
    document.getElementById('spiritual-step-partner')?.classList.remove('hidden');
    updateBackButton();
    showToast('Раунд 3: Напишите напарнику лично прямо сейчас 🤝', 'info');
});

// Кнопка открытия диалога с напарником
document.getElementById('btn-open-partner-chat')?.addEventListener('click', () => {
    if (cachedPartnerUsername) {
        const cleanName = cachedPartnerUsername.replace('@', '').trim();
        const tgUrl = `https://t.me/${cleanName}`;
        if (window.Telegram && Telegram.WebApp && Telegram.WebApp.openTelegramLink) {
            Telegram.WebApp.openTelegramLink(tgUrl);
        } else if (window.Telegram && Telegram.WebApp && Telegram.WebApp.openLink) {
            Telegram.WebApp.openLink(tgUrl);
        } else {
            window.open(tgUrl, '_blank');
        }
    } else {
        showToast('Откройте диалог с напарником в Telegram и напишите ему о вашей ситуации 💬', 'info');
    }
});

// Кнопка подтверждения «Я написал напарнику лично» (Стрик сохранен!)
document.getElementById('btn-confirm-partner-contacted')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-confirm-partner-contacted');
    btn.disabled = true;
    try {
        await apiFetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'partner_contacted' })
        });
    } catch (e) {
        console.error(e);
    }
    
    hapticNotification('success');
    showToast('Ты поступил мудро и зрело! Стрик сохранен. Держись вместе с напарником! 🤝', 'success');
    document.getElementById('sos-spiritual-content')?.classList.add('hidden');
    document.getElementById('panic-relapse-section')?.classList.remove('hidden');
    document.getElementById('sos-start-screen')?.classList.remove('hidden');
    btn.disabled = false;
    switchTab('dashboard');
});

// Ссылка на крайний случай (физический срыв)
document.getElementById('link-show-direct-relapse')?.addEventListener('click', (e) => {
    e.preventDefault();
    relapseSource = 'panic';
    document.getElementById('sos-spiritual-content')?.classList.add('hidden');
    document.getElementById('panic-relapse-section')?.classList.remove('hidden');
    document.getElementById('relapse-form')?.classList.remove('hidden');
    updateBackButton();
    showToast('Укажите триггер срыва для анализа и извлечения уроков', 'info');
});

// Кнопки показа и скрытия формы записи срыва
document.getElementById('btn-show-relapse-form')?.addEventListener('click', () => {
    relapseSource = 'direct';
    document.getElementById('relapse-form')?.classList.remove('hidden');
    updateBackButton();
});

document.getElementById('btn-cancel-relapse')?.addEventListener('click', () => {
    document.getElementById('relapse-form')?.classList.add('hidden');
    updateBackButton();
});

async function loadSpiritualSolution(tType, notes) {
    const thoughtEl = document.getElementById('spiritual-thought-text');
    const actionBox = document.getElementById('spiritual-action-box');
    const actionText = document.getElementById('spiritual-action-text');
    const catBadge = document.getElementById('spiritual-cat-badge');
    const primaryContainer = document.getElementById('spiritual-primary-card-container');
    const stepSelect = document.getElementById('spiritual-step-select');
    const stepStudy = document.getElementById('spiritual-step-study');
    const btnRead = document.getElementById('btn-spiritual-mark-read');
    const btnHelped = document.getElementById('btn-spiritual-helped');
    
    // Скрываем блок фиксации срыва во время изучения
    document.getElementById('panic-relapse-section')?.classList.add('hidden');
    
    try {
        const tTypes = Array.isArray(tType) ? tType : (tType ? [tType] : []);
        const resp = await apiFetch('/api/spiritual_help', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                temptation_types: tTypes,
                temptation_type: tTypes[0] || null,
                user_notes: notes,
                round: 1
            })
        });
        const data = await resp.json();
        
        if (data.success || data.ok) {
            if (data.partner_username) {
                cachedPartnerUsername = data.partner_username;
            }
            if (thoughtEl) {
                thoughtEl.textContent = data.spiritual_thought;
            }
            if (actionBox && actionText) {
                actionText.textContent = data.spiritual_action;
                actionBox.classList.remove('hidden');
            }
            if (catBadge) {
                catBadge.textContent = data.temptation_title || 'Духовное наставление';
            }
            
            const materials = (data.materials && data.materials.length > 0) ? data.materials : (data.primary_material ? [data.primary_material] : []);
            const primary = data.primary_material || materials[0] || {
                title: "Бог хочет, чтобы мы были чистыми",
                type_label: "wol.jw.org Урок",
                icon: "✨",
                description: "Нравственная чистота и близкие отношения с Богом.",
                url: "https://wol.jw.org/ru/wol/d/r2/lp-u/1102021240"
            };
            currentPrimaryArticleTitle = primary.title || 'Духовная публикация';
            round1ReflectionSaved = false;
            round1PromptedReflection = false;
            const refl1Input = document.getElementById('spiritual-reflection-input');
            const refl1Feedback = document.getElementById('spiritual-reflection-feedback');
            if (refl1Input) refl1Input.value = '';
            if (refl1Feedback) {
                refl1Feedback.textContent = '';
                refl1Feedback.className = 'reflection-feedback hidden';
            }
            
            if (primaryContainer) {
                let html = `
                    <div class="spiritual-card" data-url="${primary.url}" style="border-width: 2px; border-color: rgba(162, 155, 254, 0.45); background: rgba(108, 92, 231, 0.08); cursor: pointer;">
                        <div class="spiritual-badge">
                            <span>${primary.icon || '📖'}</span>
                            <span>${primary.type_label || 'wol.jw.org'}</span>
                        </div>
                        <div class="spiritual-title" style="font-size: 15px; margin-top: 2px;">${primary.title}</div>
                        <div class="spiritual-desc" style="margin-top: 4px;">${primary.description || ''}</div>
                        <div class="spiritual-btn" style="margin-top: 10px; background: rgba(108, 92, 231, 0.3); border-color: #a29bfe;">
                            <span>Открыть и изучить материал</span>
                            <span>↗</span>
                        </div>
                    </div>
                `;
                
                if (materials.length > 1) {
                    html += `
                        <div style="margin-top: 14px; margin-bottom: 8px; font-size: 11px; font-weight: 700; color: #a29bfe; text-transform: uppercase; letter-spacing: 0.5px;">
                            📚 Дополнительные материалы по выбранным темам:
                        </div>
                    `;
                    for (let i = 1; i < materials.length; i++) {
                        const m = materials[i];
                        html += `
                            <div class="spiritual-card" data-url="${m.url}" style="margin-top: 8px; border-width: 1px; border-color: rgba(162, 155, 254, 0.3); background: rgba(255, 255, 255, 0.03); cursor: pointer;">
                                <div class="spiritual-badge" style="background: rgba(255, 255, 255, 0.08); color: #dfe6e9;">
                                    <span>${m.icon || '📖'}</span>
                                    <span>${m.type_label || 'wol.jw.org'}</span>
                                </div>
                                <div class="spiritual-title" style="font-size: 14px; margin-top: 2px;">${m.title}</div>
                                <div class="spiritual-desc" style="margin-top: 3px; font-size: 12px;">${m.description || ''}</div>
                                <div class="spiritual-btn" style="margin-top: 8px; font-size: 12px; padding: 6px 10px;">
                                    <span>Открыть статью</span>
                                    <span>↗</span>
                                </div>
                            </div>
                        `;
                    }
                }
                
                primaryContainer.innerHTML = html;
                
                primaryContainer.querySelectorAll('.spiritual-card').forEach(card => {
                    card.addEventListener('click', (e) => {
                        e.preventDefault();
                        const url = card.getAttribute('data-url');
                        if (!url) return;
                        if (window.Telegram && Telegram.WebApp && Telegram.WebApp.openLink) {
                            Telegram.WebApp.openLink(url);
                        } else {
                            window.open(url, '_blank');
                        }
                    });
                });
            }
            // Переключаем шаги
            stepSelect?.classList.add('hidden');
            stepStudy?.classList.remove('hidden');
            updateBackButton();
            return;
        }
        showToast(data.error || 'Ошибка при подборе духовного решения', 'error');
    } catch (e) {
        console.error('Error loading spiritual solution:', e);
        showToast('Ошибка при подборе духовного решения', 'error');
    }
}

async function loadRound2Solution(tType, notes) {
    const thoughtEl = document.getElementById('round2-thought-text');
    const actionBox = document.getElementById('round2-action-box');
    const actionText = document.getElementById('round2-action-text');
    const cardContainer = document.getElementById('round2-card-container');
    
    try {
        const tTypes = Array.isArray(tType) ? tType : (tType ? [tType] : []);
        const resp = await apiFetch('/api/spiritual_help', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                temptation_types: tTypes,
                temptation_type: tTypes[0] || null,
                user_notes: notes,
                round: 2
            })
        });
        const data = await resp.json();
        
        if (data.success || data.ok) {
            if (data.partner_username) {
                cachedPartnerUsername = data.partner_username;
            }
            if (thoughtEl) {
                thoughtEl.textContent = data.spiritual_thought;
            }
            if (actionBox && actionText) {
                actionText.textContent = data.spiritual_action;
                actionBox.classList.remove('hidden');
            }
            
            const materials = (data.materials && data.materials.length > 0) ? data.materials : (data.primary_material ? [data.primary_material] : []);
            const secondary = data.primary_material || materials[0] || {
                title: "Бог хочет, чтобы мы были чистыми",
                type_label: "wol.jw.org Урок",
                icon: "✨",
                description: "Нравственная чистота и близкие отношения с Богом.",
                url: "https://wol.jw.org/ru/wol/d/r2/lp-u/1102021240"
            };
            currentRound2ArticleTitle = secondary.title || 'Углубленный материал';
            round2ReflectionSaved = false;
            round2PromptedReflection = false;
            const refl2Input = document.getElementById('round2-reflection-input');
            const refl2Feedback = document.getElementById('round2-reflection-feedback');
            if (refl2Input) refl2Input.value = '';
            if (refl2Feedback) {
                refl2Feedback.textContent = '';
                refl2Feedback.className = 'reflection-feedback hidden';
            }
            
            if (cardContainer) {
                let html = `
                    <div class="spiritual-card" data-url="${secondary.url}" style="border-width: 2px; border-color: rgba(253, 203, 110, 0.45); background: rgba(253, 203, 110, 0.08); cursor: pointer;">
                        <div class="spiritual-badge" style="background: rgba(253, 203, 110, 0.2); color: #ffeaa7;">
                            <span>${secondary.icon || '🛡️'}</span>
                            <span>${secondary.type_label || 'wol.jw.org'}</span>
                        </div>
                        <div class="spiritual-title" style="font-size: 15px; margin-top: 2px;">${secondary.title}</div>
                        <div class="spiritual-desc" style="margin-top: 4px;">${secondary.description || ''}</div>
                        <div class="spiritual-btn" style="margin-top: 10px; background: rgba(253, 203, 110, 0.25); border-color: #fdcb6e; color: #ffeaa7;">
                            <span>Открыть и изучить материал Раунда 2</span>
                            <span>↗</span>
                        </div>
                    </div>
                `;
                
                if (materials.length > 1) {
                    html += `
                        <div style="margin-top: 14px; margin-bottom: 8px; font-size: 11px; font-weight: 700; color: #fdcb6e; text-transform: uppercase; letter-spacing: 0.5px;">
                            📚 Дополнительные материалы Раунда 2:
                        </div>
                    `;
                    for (let i = 1; i < materials.length; i++) {
                        const m = materials[i];
                        html += `
                            <div class="spiritual-card" data-url="${m.url}" style="margin-top: 8px; border-width: 1px; border-color: rgba(253, 203, 110, 0.3); background: rgba(255, 255, 255, 0.03); cursor: pointer;">
                                <div class="spiritual-badge" style="background: rgba(255, 255, 255, 0.08); color: #dfe6e9;">
                                    <span>${m.icon || '🛡️'}</span>
                                    <span>${m.type_label || 'wol.jw.org'}</span>
                                </div>
                                <div class="spiritual-title" style="font-size: 14px; margin-top: 2px;">${m.title}</div>
                                <div class="spiritual-desc" style="margin-top: 3px; font-size: 12px;">${m.description || ''}</div>
                                <div class="spiritual-btn" style="margin-top: 8px; font-size: 12px; padding: 6px 10px; background: rgba(253, 203, 110, 0.15); border-color: #fdcb6e; color: #ffeaa7;">
                                    <span>Открыть статью</span>
                                    <span>↗</span>
                                </div>
                            </div>
                        `;
                    }
                }
                
                cardContainer.innerHTML = html;
                updateBackButton();
                
                cardContainer.querySelectorAll('.spiritual-card').forEach(card => {
                    card.addEventListener('click', (e) => {
                        e.preventDefault();
                        const url = card.getAttribute('data-url');
                        if (!url) return;
                        if (window.Telegram && Telegram.WebApp && Telegram.WebApp.openLink) {
                            Telegram.WebApp.openLink(url);
                        } else {
                            window.open(url, '_blank');
                        }
                    });
                });
            }
        } else {
            showToast(data.error || 'Ошибка при загрузке 2-го раунда', 'error');
        }
    } catch (e) {
        console.error('Error loading round 2 solution:', e);
        showToast('Ошибка при загрузке 2-го раунда', 'error');
    }
}

// 5. Обработка селекта причин (вывод текстового поля для "Другое")
document.getElementById('relapse-trigger')?.addEventListener('change', (e) => {
    hapticSelection();
    const val = e.target.value;
    const otherGroup = document.getElementById('other-trigger-group');
    if (val === 'Другое') {
        otherGroup?.classList.remove('hidden');
    } else {
        otherGroup?.classList.add('hidden');
    }
});

// 6. Подтверждение и отправка срыва
document.getElementById('btn-submit-relapse')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-submit-relapse');
    const triggerSelect = document.getElementById('relapse-trigger');
    const otherInput = document.getElementById('other-trigger-input');
    
    let triggerValue = triggerSelect?.value || 'Скука / Безделье';
    if (triggerValue === 'Другое') {
        const text = (otherInput?.value || '').trim();
        if (text.length < 3) {
            hapticNotification('error');
            showToast('Пожалуйста, опишите причину подробнее', 'error');
            return;
        }
        triggerValue = `Другое: ${text}`;
    }
    
    btn.disabled = true;
    btn.textContent = 'Обработка...';
    
    try {
        const endpoint = '/api/relapse';
        const bodyPayload = { trigger_reason: triggerValue, source: relapseSource };
        
        const response = await apiFetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bodyPayload)
        });
        
        let resData = null;
        try {
            resData = await response.json();
        } catch (parseErr) {
            console.error('JSON parse error on /api/relapse:', parseErr);
            hapticNotification('error');
            showToast(`Ошибка сервера (${response.status}) при сохранении срыва`, 'error');
            return;
        }

        if (response.ok && resData && resData.success) {
            hapticNotification('success');
            if (resData.confession_pending) {
                showToast(resData.message, 'info');
            } else {
                showToast(resData.message || 'Счетчик сброшен. Пожалуйста, откройте чат бота.');
            }
            
            // Очищаем форму и возвращаем исходное состояние
            relapseSource = 'direct';
            document.getElementById('relapse-form')?.classList.add('hidden');
            document.getElementById('sos-dynamic-content')?.classList.add('hidden');
            document.getElementById('sos-spiritual-content')?.classList.add('hidden');
            document.getElementById('panic-relapse-section')?.classList.remove('hidden');
            document.getElementById('sos-start-screen')?.classList.remove('hidden');
            document.getElementById('sos-guidelines-box')?.classList.remove('hidden');
            if (otherInput) otherInput.value = '';
            if (triggerSelect) triggerSelect.value = 'Скука / Безделье';
            document.getElementById('other-trigger-group')?.classList.add('hidden');
            
            // Перезагружаем данные и выводим дашборд
            await loadAllData();
            switchTab('dashboard');
            
            // По возможности закрываем Mini App, чтобы пользователь сразу зашел в чат
            if (tg) {
                setTimeout(() => tg.close(), 2500);
            }
        } else {
            hapticNotification('error');
            showToast((resData && resData.error) || `Ошибка сохранения срыва (${response.status})`, 'error');
        }
    } catch (err) {
        console.error(err);
        hapticNotification('error');
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

// Глобальная делегация виброотклика на кнопки и элементы выбора
document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn, .nav-item, .chip-btn');
    if (btn) {
        if (btn.classList.contains('nav-item') || btn.classList.contains('chip-btn')) {
            hapticSelection();
        } else {
            hapticImpact('light');
        }
    }
});

// Запуск при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    checkDefaultTab();
    loadAllData();
    initHomeScreenShortcut();
    updateBackButton();
});