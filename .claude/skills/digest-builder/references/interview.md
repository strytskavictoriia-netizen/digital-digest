# Interview for a new digest

Goal: fill `title`, `emoji`, `language`, `topic`, `audience`, `rubrics` and `format` in `config.yaml`.
Ask in two or three short rounds, not one long questionnaire. Offer a concrete suggestion for each
question so the user can answer "так" — most people don't know what they want until they see it.
If the user is unsure, start narrow: it is easy to widen a digest later, and a noisy first week
kills interest.

## Round 1 — what and for whom

1. **Тема.** What is the digest about? Then immediately sharpen it:
   - what MUST be included (e.g. "нові інструменти", "кейси компаній", "зміни законодавства");
   - what must NOT be included (politics, funding rounds, gossip, research without practical use…).
   Write both lists into `topic` — explicit include/exclude lists are what keeps the digest focused.
2. **Для кого і навіщо.** Who reads it (the user only, a team, management)? What do they do for a
   living? What should they *do* with the news — try tools, make decisions, find clients, save money?
   This goes into `audience`; it drives the "чим корисно" line and the recommendations, so ask for
   specifics (company type, teams, current priorities). Note: the company name may appear in
   `audience` — the prompts keep it out of the public Telegraph pages.
3. **Назва і емодзі.** Suggest one, e.g. `title: "Маркетинг-дайджест"`, `emoji: "📣"`.

## Round 2 — structure

4. **Напрями (rubrics).** Propose 2–4 based on the topic. Each rubric has `id` (latin, short),
   `emoji`, `title`, `hashtag` is not needed, and a `hint` describing what belongs there — make the
   hint concrete and mention the kinds of cases that are valuable ("ОСОБЛИВО кейси користувачів:
   що зробили, яким інструментом, як повторити"). More than 4 rubrics makes one message too long.
5. **Мова випуску.** Default: українська.

## Round 3 — format (ask every time, offer defaults)

| Option | Question | Default |
|---|---|---|
| `layout` | Як виглядає пост: **items** — усі новини рядками-посиланнями, кожна на свою сторінку; **issue** — топ-3 детально з «Для нас» + посилання на одну повну сторінку випуску? | items для коротких оглядів; issue для аналітичних із багатьма секціями |
| `max_items` | Скільки новин максимум? Для items усе має влізти в одне повідомлення. | items: 10–12 (max 14); issue: до 20 |
| `top_count` | (issue) Скільки головних новин детально в пості? | 3 |
| `item_pages` | (items) Окрема сторінка Telegraph з подробицями на кожну новину? | так |
| `idea_of_day` | Блок «💡 Ідея дня»? | так |
| `tests` | Блок «🧪 Що протестувати» — 2–4 гіпотези з випуску? | ні (так для дайджестів «що робити») |
| `rejected_footer` | На сторінці випуску — «що перевірили й відкинули і чому»? | ні |
| `weekly` | Тижневий підсумок? Якого дня й о котрій? | так, п'ятниця 15:00 |
| time | О котрій публікувати щоденний випуск (за Києвом)? | 08:10 |

Explain Telegraph honestly: pages are public to anyone who has the link (URLs are random and
unguessable), the company is never named there; the "для нас" lines, the idea and the tests stay
only in the private channel.

## Optional quality features (offer them for analytical / business digests)

- **Trust tiers** — give sources `tier: T1|T2|T3|T4|UA` (official / press / research / insiders /
  Ukrainian). The prompt then requires at least one T1–T3 source per item and marks unconfirmed
  figures with «⚠️ Не підтверджено». Good when numbers matter (rates, prices, deals).
- **Reference file** — `reference: reference.md` with stable facts (rates, terms, policies). The
  model treats them as known background: it won't present them as news, and flags changes.
  Write it with the user from what they already know; keep it to a few screens.
- If the user brings a methodology document (filters, blacklist, sections, source registry),
  translate it faithfully: filters and blacklist → `topic`; business directions → `audience`;
  sections → `rubrics` with concrete hints; source registry → sources with tiers; stable facts →
  reference file.

Also mention the model: `claude-sonnet-5` by default (saves subscription limits); `claude-opus-5`
gives deeper analysis but uses limits several times faster.

## Example of a filled config head

```yaml
title: "Маркетинг-дайджест"
emoji: "📣"
language: українська
format:
  max_items: 10
  item_pages: true
  idea_of_day: true
  weekly: true
topic: |
  Практичний маркетинг для e-commerce: реклама (Meta, Google, TikTok), email, контент, аналітика.
  Включай: нові інструменти й функції рекламних кабінетів, зміни алгоритмів і правил, кейси з цифрами.
  НЕ включай: загальні новини компаній, фінансові раунди, політику, мотиваційні колонки.
audience: |
  Маркетингова команда інтернет-магазину одягу (5 людей), керівник маркетингу.
  Хочуть: знаходити робочі прийоми, економити бюджет, швидко реагувати на зміни платформ.
rubrics:
  - id: ads
    emoji: "🎯"
    title: Реклама
    hint: Meta, Google, TikTok Ads — нові формати, зміни правил, кейси з цифрами
  - id: content
    emoji: "✍️"
    title: Контент і email
    hint: інструменти й прийоми для контенту, розсилок, соцмереж; ОСОБЛИВО кейси з результатами
```
