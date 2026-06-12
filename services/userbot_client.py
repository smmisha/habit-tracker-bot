import logging

logger = logging.getLogger(__name__)

class BusinessConnectionClient:
    """
    Класс-заглушка под старое имя для отправки сообщений 
    через официальное Бизнес-подключение (Автоматизация чатов)
    """
    async def send_message_to_partner(self, business_connection_id: str, partner_username: str, text: str) -> bool:
        """Отправка сообщения напарнику от лица пользователя через Telegram Business connection"""
        from main import bot
        if not business_connection_id:
            logger.warning("Попытка отправки сообщения без business_connection_id")
            return False
            
        try:
            username = partner_username.replace("@", "").strip()
            
            # Если передан цифровой ID, преобразуем в int, иначе используем как юзернейм
            if username.isdigit() or (username.startswith("-") and username[1:].isdigit()):
                target_chat = int(username)
            else:
                target_chat = f"@{username}"
                
            # Отправляем сообщение от лица пользователя
            await bot.send_message(
                chat_id=target_chat,
                text=text,
                business_connection_id=business_connection_id
            )
            logger.info(f"Сообщение напарнику @{username} успешно отправлено через Бизнес-аккаунт.")
            return True
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение напарнику @{partner_username} через Бизнес-аккаунт: {e}")
            
            # Резервный вариант: пробуем отправить сообщение напрямую от лица бота
            try:
                logger.info(f"Попытка отправить резервное сообщение напарнику @{partner_username} напрямую от лица бота...")
                await bot.send_message(
                    chat_id=target_chat,
                    text=text
                )
                logger.info(f"Сообщение напарнику @{partner_username} успешно отправлено напрямую от лица бота (fallback).")
                return True
            except Exception as fallback_err:
                logger.error(f"Не удалось отправить резервное сообщение напрямую от лица бота: {fallback_err}")
                
            return False

userbot = BusinessConnectionClient()
