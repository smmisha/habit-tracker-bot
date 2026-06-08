// Инициализация Telegram WebApp
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand(); // Расширяем на весь экран
    tg.ready();
}

// Извлекаем user_id
function getUserId() {
    // 1. Пробуем получить из WebApp SDK
    if (tg?.initDataUnsafe?.user?.id) {
        return tg.initDataUnsafe.user.id;
    }
    // 2. Пробуем получить из GET-параметров URL
    const urlParams = new URLSearchParams(window.location.search);
    const paramId = urlParams.get('user_id');
    if (paramId) {
        return paramId;
    }
    // 3. Резервный ID для локального тестирования в браузере (наш пользователь)
    return '5037862619';
}

const userId = getUserId();

// Загрузка статистики с бэкенда
async function loadDashboardData() {
    try {
        const response = await fetch(`/api/stats?user_id=${userId}`);
        if (!response.ok) {
            throw new Error(`Ошибка загрузки данных: ${response.status}`);
        }
        
        const data = await response.json();
        renderStats(data);
        renderCalendar(data.calendar_days);
        renderChart(data.triggers);
    } catch (error) {
        console.error('Ошибка:', error);
        // Заглушка на случай ошибок
        document.getElementById('current-streak').textContent = 'Ошибка';
        document.getElementById('total-relapses').textContent = 'Ошибка';
    }
}

// Отображение общей статистики
function renderStats(data) {
    document.getElementById('current-streak').textContent = data.streak_str || '0 дней';
    document.getElementById('total-relapses').textContent = data.total_relapses ?? '0';
}

// Рендеринг сетки календаря
function renderCalendar(days) {
    const grid = document.getElementById('calendar-grid');
    grid.innerHTML = ''; // Очищаем старый календарь
    
    if (!days || days.length === 0) {
        grid.innerHTML = '<div style="grid-column: span 7; text-align: center; color: var(--text-secondary);">Нет данных за этот месяц</div>';
        return;
    }
    
    days.forEach(day => {
        const dayEl = document.createElement('div');
        dayEl.className = 'calendar-day';
        
        // Преобразуем строковую дату в объект для отображения числа
        const dateObj = new Date(day.date);
        const dayNumber = dateObj.getDate();
        
        dayEl.innerHTML = `<span>${dayNumber}</span>`;
        
        // Добавляем класс в зависимости от статуса
        if (day.status === 'clean') {
            dayEl.classList.add('day-clean');
        } else if (day.status === 'relapsed') {
            dayEl.classList.add('day-relapse');
            // Если срывов было больше 1, выводим количество под числом
            if (day.relapse_count > 1) {
                const subLabel = document.createElement('span');
                subLabel.className = 'day-label-sub';
                subLabel.innerHTML = `x${day.relapse_count}`;
                dayEl.appendChild(subLabel);
            }
        } else {
            dayEl.classList.add('day-no-data');
        }
        
        // Подсказка (tooltip) при наведении
        const formattedDate = dateObj.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
        let tooltipText = `${formattedDate}: `;
        if (day.status === 'clean') {
            tooltipText += 'Чистый день! 💪';
        } else if (day.status === 'relapsed') {
            tooltipText += `Срывов: ${day.relapse_count} ⚠️`;
        } else {
            tooltipText += 'Нет отметок 💤';
        }
        dayEl.title = tooltipText;
        
        grid.appendChild(dayEl);
    });
}

// Рендеринг диаграммы Chart.js
let triggersChart = null;

function renderChart(triggers) {
    const canvas = document.getElementById('triggers-chart');
    const noDataMsg = document.getElementById('no-chart-data');
    
    // Проверяем, есть ли данные
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
    
    // Уничтожаем старый график перед рендером нового
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
                backgroundColor: [
                    '#ff3b30', // Красный
                    '#ff9500', // Оранжевый
                    '#af52de', // Фиолетовый
                    '#5856d6', // Синий
                    '#007aff', // Голубой
                    '#34c759'  // Зеленый
                ],
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
                        color: '#8f92a1',
                        font: {
                            family: 'Outfit',
                            size: 11
                        },
                        padding: 15
                    }
                }
            },
            cutout: '70%'
        }
    });
}

// Запуск при загрузке страницы
document.addEventListener('DOMContentLoaded', loadDashboardData);
