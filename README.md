# Детекция взрослых бабочек

Команда собрала 400 фотографий iNaturalist с лицензией CC0. После разметки и независимой проверки получился эталон из 197 бабочек на 191 фото. На остальных 209 фото взрослых бабочек нет.

| Лучший вариант каждой модели | Precision | Recall | F1 при IoU ≥ 0,50 | F1 при IoU ≥ 0,75 | Секунд на фото |
|---|---:|---:|---:|---:|---:|
| Qwen3-VL-2B-Instruct | 0,933 | 0,985 | **0,958** | 0,795 | 0,82 |
| OWLv2 base | 0,874 | 0,843 | 0,858 | 0,522 | 0,49 |
| Grounding DINO tiny | 0,644 | 0,807 | 0,716 | 0,622 | 0,14 |

Выбрали Qwen с коротким запросом (`qwen_simple`). На тех же 400 фото замена подробного запроса на короткий снизила число лишних рамок с 76 до 14 при тех же 194 найденных бабочках. На [фото с жуком](data/images/759941099.jpg) подробный запрос дал лишнюю рамку, короткий вернул пустой ответ. На [фото с тремя бабочками](data/images/759487062.jpg) Qwen нашёл двух, Grounding DINO одну, OWLv2 ни одной. [Полный лидерборд](experiments/leaderboard.csv) · [Результаты по группам](experiments/by_group.csv)

- **Данные.** [Сбор и состав выборки](data_collection/README.md), [авторы, ссылки и лицензии](data_collection/main/photos.tsv), [400 оригиналов](data/images/), [итоговые рамки](data/annotations.jsonl). В JSONL одна строка на `photo_id`, координаты заданы в долях ширины и высоты фото.
- **Разметка.** [Проекты, инструкции, допуск, ревью и исправления](annotation/README.md). Расходы с комиссией составили 845,25 ₽. [Смета по этапам](annotation/budget.tsv)
- **Модели.** [Все промпты, пороги и результаты](experiments/README.md), [финальные предсказания](experiments/predictions/), [журнал ошибок и повторных попыток](experiments/retries.jsonl).

## Контест

За каждую из трёх посылок в таблице команда получила 10/10. [Задача в Контесте](https://contest.yandex.ru/contest/103082/)

| Посылка | Промпт | Порог уверенности |
|---|---|---:|
| [Qwen3-VL-2B-Instruct](contest/01_Qwen3-VL-2B_adult-butterflies_exclude-moths.jsonl) | Найти всех взрослых бабочек Papilionoidea, исключить моль. [Полный промпт `qwen_old`](experiments/plan.json) | без порога |
| [OWLv2 base](contest/02_OWLv2-base_adult-butterfly_thr-0.45.jsonl) | `a photo of an adult butterfly` | 0,45 |
| [Grounding DINO tiny](contest/03_Grounding-DINO-tiny_butterfly_thr-0.55.jsonl) | `butterfly.` | 0,55 |

На тех же 400 фото Контеста получили предсказания с настройками, выбранными на 300 командных фото. [Qwen с коротким промптом](contest/final/01_Qwen3-VL-2B_butterfly_simple.jsonl) · [OWLv2 с порогом 0,46](contest/final/02_OWLv2-base_adult-butterfly_thr-0.46.jsonl) · [Grounding DINO с запросом `butterfly or moth.` и порогом 0,57](contest/final/03_Grounding-DINO-tiny_butterfly-or-moth_thr-0.57.jsonl)

## Запуск

Из корня репозитория на Python 3.11. Пересчитать лидерборд и метрики по группам на CPU:

```sh
python src/evaluate.py --output recomputed
```

Инференс на NVIDIA GPU. Первая команда ставит зависимости, вторая запускает все конфигурации на командных фото, третья запускает три модели с настройками посылок в Контест.

```sh
python -m pip install -r requirements-gpu.txt
python src/infer.py --variant all
python src/infer.py --contest --variant all
```

Для одного варианта укажите, например, `--variant qwen_simple`. Выходные файлы лежат в `runs_local/predictions/` и `runs_local/contest/predictions/`. После прогона всех конфигураций команда `python src/sweep.py` повторяет подбор порогов детекторов по сохранённым кандидатам. Порог выбирали на 300 фото по F1 при IoU ≥ 0,50, при равенстве - по F1 при IoU ≥ 0,75, затем по меньшему порогу. Итоговые метрики выше посчитаны на всех 400 фото.
