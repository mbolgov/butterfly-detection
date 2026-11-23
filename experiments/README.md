# Промпты и пороги

На 400 фотографиях команды сравнили 20 вариантов промптов для трёх моделей. В таблицах ниже F1 посчитан по всем 400 фото при IoU ≥ 0,50. Лучший результат у Qwen с коротким запросом (`qwen_simple`, F1 = 0,958). [Все метрики](leaderboard.csv) · [Метрики по пяти группам фотографий](by_group.csv)

**Жирным выделены конфигурации, отправленные в Контест.** F1 в этих строках рассчитан на тех же 400 фото команды. На отдельном тесте Контеста каждая посылка получила 10/10.

## Как выбирали порог

Для каждого запроса Grounding DINO и OWLv2 сохранили рамки с уверенностью от 0,10. На одних и тех же 300 фото перебрали 91 порог от 0,10 до 1,00 с шагом 0,01. Выбирали порог с наибольшим F1 при IoU ≥ 0,50. При равенстве смотрели на F1 при IoU ≥ 0,75, а если совпадал и он, брали меньший порог. В лидерборде `f1_dev` относится к этим 300 фото, `f1_holdout` - к оставшимся 100. [Код подбора](../src/sweep.py)

Порог уверенности определяет, какие рамки оставить. Отдельно подавляли дубли с помощью NMS. У обоих детекторов при IoU между предсказанными рамками выше 0,50 оставляли рамку с большей уверенностью. Для Qwen порог NMS составлял 0,95. При оценке качества IoU считали уже между предсказанием и эталоном.

## Grounding DINO tiny

Промпт передавали одной строкой, сохраняя точки. Исходный порог уверенности в конфигурации модели - 0,25, отдельный текстовый порог (`text_threshold`) - 0,25.

| Вариант | Точный запрос | Порог уверенности | F1 на фото команды |
|---|---|---:|---:|
| `dino_joint` | `butterfly or moth.` | 0,57 | 0,716 |
| `dino_old` | `butterfly.` | 0,78 | 0,706 |
| `dino_adult` | `adult butterfly. adult moth.` | 0,41 | 0,706 |
| `dino_moth` | `butterfly. moth.` | 0,46 | 0,688 |
| **`dino_old` · [Посылка в Контест](../contest/03_Grounding-DINO-tiny_butterfly_thr-0.55.jsonl)** | **`butterfly.`** | **0,55** | **0,672** |
| `dino_poses` | `butterfly. moth. butterfly with spread wings. butterfly with folded wings. moth with spread wings. moth with folded wings.` | 0,29 | 0,555 |

## OWLv2 base

В одном запуске модель получала список запросов. В таблице отдельные запросы перечислены через запятую. Исходный порог уверенности в конфигурации модели - 0,20.

| Вариант | Точный запрос | Порог уверенности | F1 на фото команды |
|---|---|---:|---:|
| `owlv2_old` | `a photo of an adult butterfly` | 0,46 | 0,858 |
| **`owlv2_old` · [Посылка в Контест](../contest/02_OWLv2-base_adult-butterfly_thr-0.45.jsonl)** | **`a photo of an adult butterfly`** | **0,45** | **0,854** |
| `owlv2_names` | `butterfly`, `moth` | 0,48 | 0,850 |
| `owlv2_poses` | `a photo of an adult butterfly`, `a photo of an adult moth`, `a butterfly with its wings folded`, `a butterfly with its wings spread`, `a moth with its wings folded`, `a moth with its wings spread` | 0,51 | 0,847 |
| `owlv2_moth` | `a photo of an adult butterfly`, `a photo of an adult moth` | 0,45 | 0,841 |
| `owlv2_joint` | `a photo of an adult butterfly or moth` | 0,41 | 0,832 |

## Qwen3-VL-2B-Instruct

Qwen возвращала координаты рамок в JSON. Во всех десяти вариантах меняли текст запроса, порог уверенности не применяли. Часть запросов явно просила искать и моль. Все варианты оценивали по одному эталону команды.

На тех же 400 фото `qwen_old` и `qwen_simple` нашли по 194 из 197 бабочек. С коротким запросом число лишних рамок снизилось с 76 до 14, а F1 вырос с 0,831 до 0,958.

| Вариант | Что просили у модели | F1 на фото команды |
|---|---|---:|
| `qwen_simple` | Короткая просьба найти всех бабочек | 0,958 |
| `qwen_taxon` | Уточнить таксон Lepidoptera, включая толстоголовок и молей | 0,851 |
| `qwen_neg_presence` | Совместить проверку присутствия и список похожих объектов | 0,833 |
| `qwen_presence` | Сначала убедиться, что на фото видно взрослое насекомое нужной группы | 0,833 |
| **`qwen_old` · [Посылка в Контест](../contest/01_Qwen3-VL-2B_adult-butterflies_exclude-moths.jsonl)** | **Взрослые Papilionoidea, исключить моль, плотно обвести видимые части** | **0,831** |
| `qwen_compact` | Краткое описание бабочек, молей и видимых частей тела | 0,820 |
| `qwen_moth` | Включить взрослых молей, в том числе со сложенными крыльями | 0,808 |
| `qwen_box_edges` | Провести границы по крайним точкам, исключить лишний фон | 0,778 |
| `qwen_moth_negatives` | Перечислить похожих насекомых и примеры пустого кадра | 0,745 |
| `qwen_multiple` | Проверить фон, разделять соприкасающихся особей | 0,704 |

[Полные тексты 10 промптов Qwen](#промпты-qwen)

## Посылки в Контест

Для отдельных 400 фото Контеста отправили три файла. Qwen использовала `qwen_old` без порога уверенности, OWLv2 - `owlv2_old` с порогом 0,45, Grounding DINO - `dino_old` с порогом 0,55. Все три посылки получили 10/10. [Файлы посылок](../contest/)

## Файлы эксперимента

- В [plan.json](plan.json) сохранены версии весов, параметры инференса, промпты, сетка порогов и ID 300 фото для подбора.
- В [predictions/](predictions/) лежит по одному JSONL на вариант. В каждом файле по 400 ответов на фото команды. Для Grounding DINO и OWLv2 сохранены предсказания при порогах, выбранных на 300 фото.
- Из [timings.csv](timings.csv) посчитано среднее время на фото для каждого варианта в лидерборде.
- В [retries.jsonl](retries.jsonl) записаны два ответа Qwen, которые пришлось получить повторно из-за ограничения длины вывода. При повторе `repetition_penalty` повысили с 1,0 до 1,1.

## Промпты Qwen

**qwen_simple**

> `Locate every butterfly in the image. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no butterflies, return []. Do not include explanations or markdown.`

**qwen_taxon**

> `Locate every visible adult butterfly or moth, including resting moths with folded wings. Exclude other insects, caterpillars, pupae, and shadows. Use one tight rectangular bounding box per adult butterfly or moth, including all visible wings, body, antennae and legs. Do not infer hidden or cropped parts. The target group is adult Lepidoptera, including skippers, butterflies and moths. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no adult butterflies or moths, return []. Do not include explanations or markdown.`

**qwen_neg_presence**

> `Locate every visible adult butterfly or moth, including resting moths with folded wings. Exclude other insects, caterpillars, pupae, and shadows. Bees, bumblebees, wasps, hoverflies, beetles and dragonflies are other insects. Flowers, leaves and leaf damage alone are also empty cases. Use one tight rectangular bounding box per adult butterfly or moth, including all visible wings, body, antennae and legs. Do not infer hidden or cropped parts. First check whether a visible insect is an adult butterfly or moth. A wing-like shape or a pattern on a leaf alone is insufficient. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no adult butterflies or moths, return []. Do not include explanations or markdown.`

**qwen_presence**

> `Locate every visible adult butterfly or moth, including resting moths with folded wings. Exclude other insects, caterpillars, pupae, and shadows. Use one tight rectangular bounding box per adult butterfly or moth, including all visible wings, body, antennae and legs. Do not infer hidden or cropped parts. First check whether a visible insect is an adult butterfly or moth. A wing-like shape or a pattern on a leaf alone is insufficient. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no adult butterflies or moths, return []. Do not include explanations or markdown.`

**qwen_old**

> `Locate every adult butterfly (Papilionoidea) visible in the image. Exclude moths, other insects, caterpillars, pupae, and shadows. Use one tight rectangular bounding box per butterfly, including all visible wings, body, antennae and legs. Do not infer hidden or cropped parts. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no adult butterflies, return []. Do not include explanations or markdown.`

**qwen_compact**

> `Box each visible adult butterfly or moth. Include its visible wings, body, antennae and legs. Exclude caterpillars, pupae, other insects and shadows. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no adult butterflies or moths, return []. Do not include explanations or markdown.`

**qwen_moth**

> `Locate every visible adult butterfly or moth, including resting moths with folded wings. Exclude other insects, caterpillars, pupae, and shadows. Use one tight rectangular bounding box per adult butterfly or moth, including all visible wings, body, antennae and legs. Do not infer hidden or cropped parts. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no adult butterflies or moths, return []. Do not include explanations or markdown.`

**qwen_box_edges**

> `Locate every visible adult butterfly or moth, including resting moths with folded wings. Exclude other insects, caterpillars, pupae, and shadows. Use one tight rectangular bounding box per adult butterfly or moth, including all visible wings, body, antennae and legs. Do not infer hidden or cropped parts. Place each edge at the outermost visible point of that individual on that side. Keep any flower, leaf or perch outside the box where possible without clipping the insect. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no adult butterflies or moths, return []. Do not include explanations or markdown.`

**qwen_moth_negatives**

> `Locate every visible adult butterfly or moth, including resting moths with folded wings. Exclude other insects, caterpillars, pupae, and shadows. Bees, bumblebees, wasps, hoverflies, beetles and dragonflies are other insects. Flowers, leaves and leaf damage alone are also empty cases. Use one tight rectangular bounding box per adult butterfly or moth, including all visible wings, body, antennae and legs. Do not infer hidden or cropped parts. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no adult butterflies or moths, return []. Do not include explanations or markdown.`

**qwen_multiple**

> `Locate every visible adult butterfly or moth, including resting moths with folded wings. Exclude other insects, caterpillars, pupae, and shadows. Use one tight rectangular bounding box per adult butterfly or moth, including all visible wings, body, antennae and legs. Do not infer hidden or cropped parts. Scan the entire image for additional individuals, including small ones in the background. Two touching individuals each get their own box. Two wings of the same insect share one box. Return only a JSON array, with one object per butterfly: {"bbox_2d": [x_min, y_min, x_max, y_max], "label": "butterfly"}. Coordinates must be integers from 0 to 1000, normalized independently by the full image width and height. The first pair is the top-left corner; the second is the bottom-right corner. If there are no adult butterflies or moths, return []. Do not include explanations or markdown.`
