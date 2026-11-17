const tg = window.Telegram.WebApp;
tg.expand();

// ЗАМЕНИ НА СВОЮ ССЫЛКУ RENDER
const API_URL = "https://casino-bot-0eke.onrender.com"; 

let currentUser = null;

// Инициализация
async function init() {
    if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
        document.getElementById('user-name').innerText = tg.initDataUnsafe.user.first_name;
    }

    // Отправляем запрос на бэкенд
    try {
        const response = await fetch(`${API_URL}/api/user`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ initData: tg.initData })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentUser = data.user;
            updateUI(data.user);
        } else {
            console.error("Auth error:", data.error);
            tg.showAlert("Ошибка авторизации. Попробуйте перезайти.");
        }
    } catch (e) {
        console.error(e);
        tg.showAlert("Сервер недоступен.");
    }

    document.getElementById('loading').classList.remove('active');
    document.getElementById('wallet-screen').classList.add('active');
    drawChart();
}

function updateUI(user) {
    document.getElementById('balance-tokens').innerText = user.balance.toLocaleString('ru-RU');
    document.getElementById('balance-tnc').innerText = user.balance_tnc.toFixed(8);
}

// Переключение вкладок
function switchTab(tab) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    
    if (tab === 'wallet') {
        document.getElementById('wallet-screen').classList.add('active');
    } else if (tab === 'games') {
        document.getElementById('games-screen').classList.add('active');
    }
    tg.HapticFeedback.impactOccurred('light');
}

// Обмен
async function swap(direction) {
    const amountStr = prompt("Введите количество для обмена:");
    if (!amountStr) return;
    const amount = parseFloat(amountStr);
    if (isNaN(amount) || amount <= 0) return tg.showAlert("Неверная сумма");

    try {
        const response = await fetch(`${API_URL}/api/swap`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                initData: tg.initData,
                amount: amount,
                direction: direction 
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            tg.showAlert(`Успешно обменяно!`);
            tg.HapticFeedback.notificationOccurred('success');
            // Перезапрашиваем баланс
            init();
        } else {
            tg.showAlert(`Ошибка: ${data.error}`);
            tg.HapticFeedback.notificationOccurred('error');
        }
    } catch (e) {
        tg.showAlert("Ошибка сервера");
    }
}

function openGame(name) {
    tg.showAlert(`Игра ${name} доступна в нашем чате!`);
}

// Рисуем график (заглушка)
function drawChart() {
    const ctx = document.getElementById('chart').getContext('2d');
    // Тут можно подключить Chart.js, но для простоты рисуем градиент
    const gradient = ctx.createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, 'rgba(94, 156, 255, 0.5)');
    gradient.addColorStop(1, 'rgba(94, 156, 255, 0)');
    
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.moveTo(0, 150);
    ctx.lineTo(50, 100);
    ctx.lineTo(100, 120);
    ctx.lineTo(150, 80);
    ctx.lineTo(200, 50);
    ctx.lineTo(250, 90);
    ctx.lineTo(300, 40);
    ctx.lineTo(300, 200);
    ctx.lineTo(0, 200);
    ctx.fill();
}

// Запуск
init();