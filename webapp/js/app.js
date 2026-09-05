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
let isSosUnlocked = false;

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
        if (!isSosUnlocked) {
            initiatePanicTimer();
            openCognitiveLock();
        }
    }
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
                tooltipText += `Чисто, опоздание (${day.excuse_reason}) ⏰`;
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

// --- COGNITIVE LOCK LOGIC ---
let currentPuzzleAnswer = null;

// Функция генерации случайного математического примера или логической последовательности
function generatePuzzle() {
    const puzzleText = document.getElementById('puzzle-text');
    const puzzleType = Math.floor(Math.random() * 3); // 0: математика, 1: последовательность, 2: логическая загадка
    
    // Сброс стилей к дефолтным (для формул)
    puzzleText.style.fontSize = "20px";
    puzzleText.style.fontWeight = "700";
    puzzleText.style.lineHeight = "1.2";
    puzzleText.style.textAlign = "center";
    
    if (puzzleType === 0) {
        const operations = ['+', '-'];
        const op1 = operations[Math.floor(Math.random() * operations.length)];
        
        let num1, num2, num3, text, ans;
        if (Math.random() > 0.5) {
            // Умножение + сложение/вычитание
            num1 = Math.floor(Math.random() * 8) + 6; // 6-13
            num2 = Math.floor(Math.random() * 6) + 3; // 3-8
            num3 = Math.floor(Math.random() * 20) + 5; // 5-24
            
            if (op1 === '+') {
                text = `${num1} * ${num2} + ${num3}`;
                ans = num1 * num2 + num3;
            } else {
                const prod = num1 * num2;
                if (prod > num3) {
                    text = `${num1} * ${num2} - ${num3}`;
                    ans = prod - num3;
                } else {
                    text = `${num3} + ${num1} * ${num2}`;
                    ans = num3 + prod;
                }
            }
        } else {
            // Деление + сложение/вычитание
            const divisors = [2, 3, 4, 5];
            const div = divisors[Math.floor(Math.random() * divisors.length)];
            const quotient = Math.floor(Math.random() * 12) + 5; // 5-16
            num1 = quotient * div;
            num2 = div;
            num3 = Math.floor(Math.random() * 20) + 5;
            
            if (op1 === '+') {
                text = `${num1} / ${num2} + ${num3}`;
                ans = quotient + num3;
            } else {
                if (quotient > num3) {
                    text = `${num1} / ${num2} - ${num3}`;
                    ans = quotient - num3;
                } else {
                    text = `${num3} - ${num1} / ${num2}`;
                    ans = num3 - quotient;
                }
            }
        }
        
        currentPuzzleAnswer = ans;
        return text;
    } else if (puzzleType === 1) {
        // Логические последовательности
        const patterns = [
            { seq: [2, 4, 8, 16], next: 32, label: '2, 4, 8, 16, ...' },
            { seq: [1, 4, 9, 16], next: 25, label: '1, 4, 9, 16, ...' },
            { seq: [3, 6, 12, 24], next: 48, label: '3, 6, 12, 24, ...' },
            { seq: [1, 2, 4, 7, 11], next: 16, label: '1, 2, 4, 7, 11, ...' },
            { seq: [2, 5, 10, 17], next: 26, label: '2, 5, 10, 17, ...' },
            { seq: [5, 10, 15, 20], next: 25, label: '5, 10, 15, 20, ...' },
            { seq: [10, 9, 7, 4], next: 0, label: '10, 9, 7, 4, ...' },
            { seq: [1, 3, 7, 15], next: 31, label: '1, 3, 7, 15, ...' }
        ];
        const selected = patterns[Math.floor(Math.random() * patterns.length)];
        currentPuzzleAnswer = selected.next;
        return `Продолжите ряд: ${selected.label}`;
    } else {
        // Логические текстовые загадки
        puzzleText.style.fontSize = "14px";
        puzzleText.style.fontWeight = "500";
        puzzleText.style.lineHeight = "1.4";
        puzzleText.style.textAlign = "left";
        
        const riddles = [
            { q: "У отца пять дочерей, у каждой дочери есть один брат. Сколько всего детей в семье?", a: 6 },
            { q: "В комнате 4 угла. В каждом углу сидит кошка. Напротив каждой кошки сидит по 3 кошки. Сколько всего кошек в комнате?", a: 4 },
            { q: "Отец старше сына в 3 раза. Вместе им 40 лет. Сколько лет сыну?", a: 10 },
            { q: "Кирпич весит 1 кг и еще полкирпича. Сколько весит один кирпич в кг?", a: 2 },
            { q: "В корзине 3 яблока. Как разделить их между тремя детьми так, чтобы одно яблоко осталось в корзине? (Введите количество яблок, которое получит последний ребенок вместе с корзиной)", a: 1 },
            { q: "На березе росло 50 яблок. Подул ветер, и 10 яблок упало. Сколько яблок осталось на березе?", a: 0 },
            { q: "Электропоезд идет на восток со скоростью 80 км/ч. Ветер дует на запад со скоростью 10 м/с. В какую сторону идет дым? (Если дыма нет, введите 0)", a: 0 },
            { q: "Горело 7 свечей. 3 свечи потушили. Сколько свечей осталось?", a: 3 },
            { q: "Улитка ползет на дерево высотой 10 метров. Днем она поднимается на 3 метра, а ночью спускается на 2 метра. За сколько дней она доползет до вершины?", a: 8 },
            { q: "В коробке лежат 10 красных и 10 синих носков. Какое минимальное количество носков нужно достать в темноте, чтобы получить хотя бы одну пару одного цвета?", a: 3 },
            { q: "Яйцо варится 5 минут. За сколько минут сварятся 5 яиц в одной кастрюле?", a: 5 },
            { q: "На руке 5 пальцев. На двух руках 10 пальцев. Сколько пальцев на 10 руках?", a: 50 },
            { q: "Шли 2 отца и 2 сына, нашли 3 апельсина. Стали делить — всем досталось по одному. Как такое возможно? Сколько человек было всего?", a: 3 },
            { q: "Ананас стоит 100 рублей и еще половину своей стоимости. Сколько рублей стоит ананас?", a: 200 },
            { q: "У трех маляров был брат Андрей, но у Андрея не было братьев. Сколько братьев было у Андрея? (Если нет, введите 0)", a: 0 }
        ];
        const selected = riddles[Math.floor(Math.random() * riddles.length)];
        currentPuzzleAnswer = selected.a;
        return selected.q;
    }
}

// Открытие модального окна когнитивного замка
function openCognitiveLock() {
    const modal = document.getElementById('cognitive-lock-modal');
    const puzzleText = document.getElementById('puzzle-text');
    const input = document.getElementById('puzzle-answer');
    
    input.value = '';
    puzzleText.textContent = generatePuzzle();
    modal.classList.add('active');
    
    setTimeout(() => input.focus(), 100);
}

// Закрытие модального окна
function closeCognitiveLock() {
    const modal = document.getElementById('cognitive-lock-modal');
    modal.classList.remove('active');
}

// Слушатель кнопки SOS (показывает когнитивный замок вместо прямого старта)
document.getElementById('btn-start-sos').addEventListener('click', () => {
    openCognitiveLock();
});

// Слушатель кнопки закрытия / отмены в модальном окне
document.getElementById('btn-close-puzzle').addEventListener('click', () => {
    closeCognitiveLock();
    // Возвращаем на дашборд, так как доступ к SOS закрыт без прохождения замка
    switchTab('dashboard');
});

// Слушатель отправки ответа в модальном окне
document.getElementById('btn-submit-puzzle').addEventListener('click', () => {
    validatePuzzleAnswer();
});

// Также проверяем ответ при нажатии Enter в поле ввода
document.getElementById('puzzle-answer').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        validatePuzzleAnswer();
    }
});

function validatePuzzleAnswer() {
    const input = document.getElementById('puzzle-answer');
    const modalContent = document.querySelector('#cognitive-lock-modal .modal-card');
    const userAnswer = parseInt(input.value.trim(), 10);
    
    if (isNaN(userAnswer)) {
        showToast('Пожалуйста, введите числовой ответ', 'error');
        return;
    }
    
    if (userAnswer === currentPuzzleAnswer) {
        showToast('Когнитивный замок успешно пройден! Мозг переключен.', 'success');
        isSosUnlocked = true; // Снимаем защиту
        closeCognitiveLock();
        startSosProcess(); // Запускаем загрузку шагов SOS
    } else {
        showToast('Неверно! Попробуйте решить новую задачу.', 'error');
        input.value = '';
        
        // Эффект тряски при ошибке
        modalContent.classList.add('shake');
        setTimeout(() => modalContent.classList.remove('shake'), 400);
        
        // Новая задача
        document.getElementById('puzzle-text').textContent = generatePuzzle();
        input.focus();
    }
}

// Отправка запроса на инициализацию таймера "тихой тревоги"
async function initiatePanicTimer() {
    try {
        await fetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, action: 'initiate' })
        });
    } catch (e) {
        console.error("Ошибка при инициализации тихой тревоги:", e);
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
}

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

// Переход от базовых SOS-шагов к духовному подкреплению (jw.org)
document.getElementById('btn-panic-failed')?.addEventListener('click', async () => {
    try {
        await fetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, action: 'failed' })
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
    showToast('Переходим к духовному подкреплению (jw.org)...', 'info');
});

// 2. Индивидуальная духовная помощь (wol.jw.org / jw.org)
// 2. Индивидуальная духовная помощь (wol.jw.org / jw.org)
let selectedTemptationTypes = [];
let currentSpiritualNotes = '';
let cachedPartnerUsername = null;
let round2TimerInterval = null;
let round2SecondsRemaining = 20 * 60;

// Обработка чипов искушений (мультивыбор)
document.querySelectorAll('#temptation-chips-container .chip-btn').forEach(btn => {
    btn.addEventListener('click', () => {
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

// Кнопка запроса духовного решения от ИИ
document.getElementById('btn-find-spiritual-solution')?.addEventListener('click', async () => {
    const btn = document.getElementById('btn-find-spiritual-solution');
    currentSpiritualNotes = document.getElementById('spiritual-user-notes')?.value || '';
    
    btn.disabled = true;
    btn.querySelector('.spinner')?.classList.remove('hidden');
    btn.querySelector('.btn-text').textContent = 'ИИ анализирует и подбирает материалы...';
    
    await loadSpiritualSolution(selectedTemptationTypes, currentSpiritualNotes);
    
    btn.disabled = false;
    btn.querySelector('.spinner')?.classList.add('hidden');
    btn.querySelector('.btn-text').textContent = '🔍 Получить духовное решение';
});

// Кнопка смены темы / возврата к выбору
document.getElementById('btn-spiritual-change-topic')?.addEventListener('click', () => {
    if (round2TimerInterval) {
        clearInterval(round2TimerInterval);
        round2TimerInterval = null;
    }
    document.getElementById('spiritual-step-study')?.classList.add('hidden');
    document.getElementById('spiritual-step-round2')?.classList.add('hidden');
    document.getElementById('spiritual-step-partner')?.classList.add('hidden');
    document.getElementById('spiritual-step-select')?.classList.remove('hidden');
});

// Раунд 1: Кнопка «Помогло! Тяга отступила»
document.getElementById('btn-spiritual-helped')?.addEventListener('click', async () => {
    try {
        await fetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, action: 'helped' })
        });
    } catch (e) {
        console.error(e);
    }
    showToast('Слава Богу! Вы устояли и защитили свой стрик! 💪', 'success');
    document.getElementById('sos-spiritual-content')?.classList.add('hidden');
    document.getElementById('panic-relapse-section')?.classList.remove('hidden');
    document.getElementById('sos-start-screen')?.classList.remove('hidden');
    switchTab('dashboard');
});

// Раунд 1: Кнопка перехода к Раунду 2 («Не помогло — Раунд 2 (погружение от 20 минут)»)
document.getElementById('btn-spiritual-to-round2')?.addEventListener('click', async () => {
    document.getElementById('spiritual-step-study')?.classList.add('hidden');
    document.getElementById('spiritual-step-round2')?.classList.remove('hidden');
    showToast('Загружаем углубленный материал Раунда 2...', 'info');
    await loadRound2Solution(selectedTemptationTypes, currentSpiritualNotes);
});

// Функции управления таймером Раунда 2
function startRound2Timer() {
    if (round2TimerInterval) {
        clearInterval(round2TimerInterval);
        round2TimerInterval = null;
    }
    
    round2SecondsRemaining = 20 * 60; // 20 минут
    updateRound2TimerDisplay();
    
    const btnHelped = document.getElementById('btn-round2-helped');
    const btnPartner = document.getElementById('btn-round2-to-partner');
    const timerStatus = document.getElementById('round2-timer-status');
    const badge = document.getElementById('round2-timer-badge');
    
    if (btnHelped) {
        btnHelped.disabled = true;
        btnHelped.style.opacity = '0.4';
    }
    if (btnPartner) {
        btnPartner.disabled = true;
        btnPartner.style.opacity = '0.4';
    }
    if (badge) {
        badge.style.background = 'rgba(253, 203, 110, 0.25)';
        badge.style.borderColor = '#fdcb6e';
        badge.style.color = '#ffeaa7';
    }
    if (timerStatus) {
        timerStatus.innerHTML = `⏳ Погрузитесь в чтение и молитву. Кнопки станут активны через <b id="round2-timer-remaining">20:00</b>`;
        timerStatus.style.color = '#fdcb6e';
    }
    
    round2TimerInterval = setInterval(() => {
        round2SecondsRemaining--;
        if (round2SecondsRemaining <= 0) {
            clearInterval(round2TimerInterval);
            round2TimerInterval = null;
            round2SecondsRemaining = 0;
            updateRound2TimerDisplay();
            
            // Разблокируем кнопки
            if (btnHelped) {
                btnHelped.disabled = false;
                btnHelped.style.opacity = '1';
                btnHelped.style.boxShadow = '0 0 15px rgba(0, 184, 148, 0.4)';
            }
            if (btnPartner) {
                btnPartner.disabled = false;
                btnPartner.style.opacity = '1';
                btnPartner.style.boxShadow = '0 0 15px rgba(116, 185, 255, 0.3)';
            }
            if (timerStatus) {
                timerStatus.innerHTML = `✅ <b>20 минут размышления завершены!</b> Оцените результат изучения:`;
                timerStatus.style.color = '#55efc4';
            }
            if (badge) {
                badge.style.background = 'rgba(0, 184, 148, 0.25)';
                badge.style.borderColor = '#00b894';
                badge.style.color = '#55efc4';
                badge.textContent = '00:00 ✓';
            }
            showToast('20 минут размышления завершены. Выберите результат:', 'success');
        } else {
            updateRound2TimerDisplay();
        }
    }, 1000);
}

function updateRound2TimerDisplay() {
    const minutes = Math.floor(round2SecondsRemaining / 60);
    const seconds = round2SecondsRemaining % 60;
    const timeStr = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    
    const badge = document.getElementById('round2-timer-badge');
    const remainingSpan = document.getElementById('round2-timer-remaining');
    if (badge && round2SecondsRemaining > 0) {
        badge.textContent = timeStr;
    }
    if (remainingSpan) {
        remainingSpan.textContent = timeStr;
    }
}

// Раунд 2: Кнопка «Помогло! Тяга отступила»
document.getElementById('btn-round2-helped')?.addEventListener('click', async () => {
    if (round2TimerInterval) {
        clearInterval(round2TimerInterval);
        round2TimerInterval = null;
    }
    try {
        await fetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, action: 'helped' })
        });
    } catch (e) {
        console.error(e);
    }
    showToast('Слава Богу! Раунд 2 помог успокоить сердце, стрик защищен! 💪', 'success');
    document.getElementById('sos-spiritual-content')?.classList.add('hidden');
    document.getElementById('panic-relapse-section')?.classList.remove('hidden');
    document.getElementById('sos-start-screen')?.classList.remove('hidden');
    switchTab('dashboard');
});

// Раунд 2: Кнопка перехода к Раунду 3 («Не помогло — Раунд 3: Написать напарнику лично»)
document.getElementById('btn-round2-to-partner')?.addEventListener('click', () => {
    if (round2TimerInterval) {
        clearInterval(round2TimerInterval);
        round2TimerInterval = null;
    }
    document.getElementById('spiritual-step-round2')?.classList.add('hidden');
    document.getElementById('spiritual-step-partner')?.classList.remove('hidden');
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
        await fetch('/api/panic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: userId, action: 'partner_contacted' })
        });
    } catch (e) {
        console.error(e);
    }
    
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
    showToast('Укажите триггер срыва для анализа и извлечения уроков', 'info');
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
        const resp = await fetch('/api/spiritual_help', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
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
            return;
        }
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
    
    // Запускаем 20-минутный таймер Раунда 2
    startRound2Timer();
    
    try {
        const tTypes = Array.isArray(tType) ? tType : (tType ? [tType] : []);
        const resp = await fetch('/api/spiritual_help', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
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
        }
    } catch (e) {
        console.error('Error loading round 2 solution:', e);
        showToast('Ошибка при загрузке 2-го раунда', 'error');
    }
}

// 3. SOS - Не помогло -> Переход к духовному подкреплению
document.getElementById('btn-panic-failed').addEventListener('click', () => {
    document.getElementById('sos-dynamic-content')?.classList.add('hidden');
    document.getElementById('panic-relapse-section')?.classList.add('hidden');
    document.getElementById('sos-spiritual-content')?.classList.remove('hidden');
    
    // Сбрасываем к шагу 1 (выбор искушения)
    document.getElementById('spiritual-step-select')?.classList.remove('hidden');
    document.getElementById('spiritual-step-study')?.classList.add('hidden');
    document.getElementById('spiritual-step-round2')?.classList.add('hidden');
    document.getElementById('spiritual-step-partner')?.classList.add('hidden');
    
    showToast('Выберите искушение для целевой помощи 🛡️', 'info');
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
            if (resData.confession_pending) {
                showToast(resData.message, 'info');
            } else {
                showToast(resData.message || 'Счетчик сброшен. Пожалуйста, откройте чат бота.');
            }
            
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
                setTimeout(() => tg.close(), 2500); // Даем больше времени прочитать уведомление об исповеди
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
