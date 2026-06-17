from typing import Optional

DRUG_RECS = [
    {
        "triggers": ["парацетамол", "парацетамолу", "paracetamol", "acetaminophen", "панадол", "panadol", "эффералган"],
        "ru": "Принимайте после еды, запивая достаточным количеством чистой воды. Не совмещайте с алкоголем, чтобы поберечь печень! Максимальная доза для взрослых — 4 г в сутки. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте після їжі, запиваючи достатньою кількістю чистої води. Не суміщайте з алкоголем, щоб зберегти печінку! Максимальна доза для дорослих — 4 г на добу. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take after meals, drinking plenty of clean water. Do not combine with alcohol to protect your liver! The maximum daily dose for adults is 4 g. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["ибупрофен", "ібупрофен", "ibuprofen", "нурофен", "nurofen", "миг", "mig"],
        "ru": "Принимайте во время или сразу после еды, чтобы не раздражать желудок. Запивайте водой или молоком. Не сочетайте с другими противовоспалительными (НПВС) без назначения врача. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте під час або одразу після їжі, щоб не подразнювати шлунок. Запивайте водою або молоком. Не поєднуйте з іншими протизапальними (НПЗЗ) без призначення лікаря. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take during or immediately after meals to avoid stomach irritation. Drink with water or milk. Do not combine with other NSAIDs without a doctor's prescription. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["аспирин", "аспірин", "aspirin", "ацетилсалицил", "ацетилсаліцил"],
        "ru": "Принимайте строго после еды, обильно запивая водой. Противопоказан детям и подросткам из-за риска синдрома Рея. Не принимайте натощак! Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте суворо після їжі, запиваючи великою кількістю води. Протипоказаний дітям та підліткам через ризик синдрому Рея. Не приймайте натщесерце! Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take strictly after meals, drinking plenty of water. Contraindicated in children and teenagers due to the risk of Reye's syndrome. Do not take on an empty stomach! Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["но-шпа", "ношпа", "дротаверин", "drotaverine"],
        "ru": "Принимайте независимо от еды при спазмах и болях. Максимальная суточная доза — 240 мг (6 таблеток по 40 мг). С осторожностью при низком давлении. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте незалежно від їжі при спазмах та болях. Максимальна добова доза — 240 мг (6 таблеток по 40 мг). З обережністю при низькому тиску. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take regardless of meals for spasms and pain. The maximum daily dose is 240 mg (6 tablets of 40 mg). Use with caution if you have low blood pressure. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["омепразол", "омез", "omeprazole", "omez", "нольпаза", "nolpaza", "эзомепразол"],
        "ru": "Принимайте утром за 30-40 минут до завтрака, проглатывая капсулу целиком и запивая водой. Помогает снизить кислотность желудка. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте вранці за 30-40 хвилин до сніданку, проковтуючи капсулу цілою та запиваючи водою. Допомагає знизити кислотність шлунка. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take in the morning 30-40 minutes before breakfast, swallowing the capsule whole with water. Helps reduce stomach acid. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["уголь", "вугілля", "charcoal", "полисорб", "энтеросгель", "смекта", "smecta"],
        "ru": "Принимайте отдельно от других лекарств и еды (интервал должен быть не менее 1.5-2 часов), иначе адсорбент нейтрализует их действие. Запивайте большим количеством воды! Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте окремо від інших ліків та їжі (інтервал повинен бути не менше 1.5-2 годин), інакше адсорбент нейтралізує їхню дію. Запивайте великою кількістю води! Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take separately from other medications and food (with an interval of at least 1.5-2 hours), otherwise the adsorbent will neutralize their effect. Drink with plenty of water! Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["азитромицин", "азитроміцин", "azithromycin", "сумамед", "sumamed"],
        "ru": "Принимайте за 1 час до или через 2 часа после еды, так как пища снижает всасывание. Курс лечения антибиотиками важно завершить полностью, даже если стало лучше! Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте за 1 годину до або через 2 години після їжі, оскільки їжа знижує всмоктування. Курс лікування антибіотиками важливо завершити повністю, навіть якщо стало краще! Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take 1 hour before or 2 hours after meals, as food reduces absorption. It is critical to finish the entire course of antibiotic treatment, even if you feel better! Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["амоксициллин", "амоксицилін", "amoxicillin", "амоксиклав", "amoksiklav", "аугментин", "augmentin", "амоксил"],
        "ru": "Принимайте в начале еды, чтобы уменьшить побочные эффекты со стороны желудка. Завершите полный курс антибиотика, не прерывайте прием самостоятельно! Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте на початку їжі, щоб зменшити побічні ефекти з боку шлунка. Завершіть повний курс антибіотика, не переривайте прийом самостійно! Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take at the start of a meal to minimize gastrointestinal side effects. Finish the full course of the antibiotic, do not stop taking it on your own! Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["анальгин", "анальгін", "analgin", "метамизол", "metamizole", "спазмалгон", "пенталгин"],
        "ru": "Принимайте после еды, запивая водой. Используйте только как кратковременное средство от боли. Не принимайте длительными курсами без контроля врача. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте після їжі, запиваючи водою. Використовуйте лише як короткочасний засіб від болю. Не приймайте тривалими курсами без контролю лікаря. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take after meals with water. Use only as a short-term pain relief. Do not take for extended periods without medical supervision. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["супрастин", "suprastin", "тавегил", "димедрол"],
        "ru": "Принимайте во время еды, не разжевывая и запивая водой. Может вызывать выраженную сонливость, поэтому избегайте вождения автомобиля и опасных видов деятельности. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте під час їжі, не розжовуючи та запиваючи водою. Може викликати виражену сонливість, тому уникайте керування автомобілем та небезпечних видів діяльності. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take with meals, swallow whole with water. May cause significant drowsiness, so avoid driving or hazardous activities. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["валериана", "валеріана", "valerian", "пустырник", "пустирник"],
        "ru": "Принимайте за 30 минут до еды или перед сном, запивая водой. Обладает накопительным успокаивающим эффектом, который проявляется при регулярном приеме. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте за 30 хвилин до їжі або перед сном, запиваючи водою. Має накопичувальний заспокійливий ефект, який проявляється при регулярному прийомі. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take 30 minutes before meals or before bedtime, drinking with water. Has a cumulative calming effect that develops with regular use. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["панкреатин", "pancreatin", "мезим", "mezym", "креон", "creon", "фестал"],
        "ru": "Принимайте непосредственно во время или сразу после еды, не разжевывая капсулы/таблетки, запивая большим количеством воды или сока. Помогает пищеварению. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте безпосередньо під час або одразу після їжі, не розжовуючи капсули/таблетки, запиваючи великою кількістю води або соку. Допомагає травленню. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take during or immediately after meals, swallow whole, and drink with plenty of water or juice. Helps support healthy digestion. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["гидазепам", "гідазепам", "gidazepam", "феназепам"],
        "ru": "Принимайте строго по назначению врача, запивая водой. Препарат может вызывать привыкание и снижать концентрацию внимания. Не употребляйте алкоголь во время курса! Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте суворо за призначенням лікаря, запиваючи водою. Препарат може викликати звикання та знижувати концентрацію уваги. Не вживайте алкоголь під час курсу! Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take strictly as prescribed by your doctor, drinking with water. The medication can be habit-forming and may impair concentration. Do not drink alcohol during the course! Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["эсциталопрам", "есцителопрам", "escitalopram", "золофт", "zoloft", "сертралин", "sertraline", "флуоксетин"],
        "ru": "Принимайте один раз в день (утром или вечером), независимо от приема пищи. Важно принимать ежедневно в одно и то же время. Эффект наступает через 2-4 недели. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте один раз на день (вранці або ввечері), незалежно від їжі. Важливо приймати щодня в один і той самий час. Ефект настає через 2-4 тижні. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take once daily (morning or evening), regardless of food. It is important to take it at the same time every day. The therapeutic effect develops in 2-4 weeks. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["цитрамон", "citramon"],
        "ru": "Принимайте после еды, запивая водой. Не используйте при заболеваниях желудка и не сочетайте с алкоголем. Содержит кофеин, поэтому может немного повышать давление. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте після їжі, запиваючи водою. Не використовуйте при захворюваннях шлунка та не поєднуйте з алкоголем. Містить кофеїн, тому може трохи підвищувати тиск. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take after meals with water. Do not use if you have stomach problems, and avoid combining with alcohol. Contains caffeine, so it may slightly increase blood pressure. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["кеторол", "кеторолак", "ketorol", "ketorolac", "дексалгин", "dexalgin", "найз", "nise"],
        "ru": "Принимайте после еды, запивая водой. Сильное обезболивающее средство. Не принимайте дольше 5 дней подряд из-за высокого риска побочных эффектов для желудка. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте після їжі, запиваючи водою. Сильний знеболювальний засіб. Не приймайте довше 5 днів поспіль через високий ризик побічних ефектів для шлунка. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take after meals with water. A powerful painkiller. Do not take for more than 5 consecutive days due to a high risk of gastrointestinal side effects. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["нимесил", "нимесулид", "nimesil", "nimesulide"],
        "ru": "Принимайте после еды. Содержимое пакетика растворите в 100 мл теплой воды. Принимайте только при необходимости снять боль/воспаление, не более 2 раз в день. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте після їжі. Вміст пакетика розчиніть у 100 мл теплої води. Приймайте лише за необхідності зняти біль/запалення, не більше 2 разів на день. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take after meals. Dissolve the contents of the sachet in 100 ml of warm water. Take only as needed for pain/inflammation, maximum twice daily. Your Mr. Tabletus cares about you! ❤️"
    },
    {
        "triggers": ["dulsevia", "дульсевия", "duloxetine", "дулоксетин"],
        "ru": "Принимайте один раз в день в одно и то же время, независимо от приема пищи. Не прекращайте прием препарата резко без консультации с врачом. Ваш Мистер Таблетус заботится о вас! ❤️",
        "uk": "Приймайте один раз на день в один і той самий час, незалежно від їжі. Не припиняйте прийом препарату раптово без консультації з лікарем. Ваш Містер Таблетус піклується про вас! ❤️",
        "en": "Take once daily at the same time, regardless of food. Do not stop taking the drug abruptly without consulting your doctor. Your Mr. Tabletus cares about you! ❤️"
    }
]

def get_local_recommendation(medicine_name: str, lang: str = "ru") -> Optional[str]:
    cleaned = medicine_name.strip().lower()
    for item in DRUG_RECS:
        for trigger in item["triggers"]:
            if trigger in cleaned:
                return item.get(lang, item.get("ru"))
    return None
