# SMS.to (personal) v2 — Home Assistant

Integrare proprie pentru SMS.to (domeniu `smsto_personal`). Compatibilă cu HA 2026.x, inclusiv 2026.11+ (probatio).

## Instalare / actualizare
1. Înlocuiește folderul `/config/custom_components/smsto_personal` cu cel din arhivă.
2. Repornește Home Assistant. (Configurarea existentă se păstrează.)
3. Setări → Dispozitive și servicii → SMS.to (personal) → **Configurează** pentru opțiuni.

## Entități
| Entitate | Ce arată |
|---|---|
| Sold | soldul contului, în moneda contului |
| SMS-uri trimise | total mesaje |
| Status / Cost / Ora ultimului mesaj | din `/last/message` (detaliile în atribute) |
| Status / Cost ultima campanie | din `/last/campaign` |
| Ultimul raport de livrare | vine prin webhook, instant |
| Sold scăzut (binary) | ON sub pragul din opțiuni |
| Buton Actualizează | reîmprospătare imediată |
| `notify.…_sms` | pentru `notify.send_message`, la numărul implicit |

## Acțiuni (25)
**Trimitere:** `send_sms`, `send_flash_sms`, `send_viber`, `send_to_list`, `send_personalized`
— toate acceptă `scheduled_for`, `timezone`, `bypass_optout`, `callback_url`, `sender_id`.
**Cost:** `estimate_cost`, plus `estimate_only` la listă/personalizat/lookup.
**Istoric:** `get_message`, `list_messages`, `get_campaign`, `list_campaigns`.
**Numere:** `check_opt_out`, `lookup_number` (HLR).
**Contacte:** `list_lists`, `create_list`, `delete_list`, `list_contacts`, `create_contact`, `delete_contact`, `opt_in`, `opt_out`, `recent_optouts`.
**Link-uri scurte:** `create_shortlink`, `list_shortlinks`, `delete_shortlink`.
**Altele:** `refresh`.

Acțiunile de citire returnează răspunsul (`response_variable`). Cu mai multe conturi, alegi contul prin `config_entry_id`.

## Evenimente
- `smsto_personal_sent` — la fiecare trimitere (ținte, message_id, campaign_id)
- `smsto_personal_delivery_report` — raport de livrare (status, phone, cost, message_id, raw)

Rapoartele de livrare: activează „Primește rapoarte de livrare” în opțiuni (necesită URL extern sau Nabu Casa).
URL-ul webhook e afișat în fereastra de opțiuni. Dacă setezi în SMS.to un secret de semnătură, pune-l și în opțiuni.

## Exemple
```yaml
action: smsto_personal.send_sms
data:
  target: "+40712345678"
  message: Pornește centrala.
  scheduled_for: "2026-10-20 06:30:00"
```
```yaml
action: smsto_personal.estimate_cost
data:
  target: "+40712345678, +40798765432"
  message: Test
response_variable: cost
```
```yaml
action: smsto_personal.send_personalized
data:
  messages:
    - {to: "+40712345678", message: "Salut Ana, factura e 120 lei."}
    - {to: "+40798765432", message: "Salut Dan, factura e 95 lei."}
```
```yaml
trigger:
  - trigger: event
    event_type: smsto_personal_delivery_report
    event_data: {status: FAILED}
action:
  - action: persistent_notification.create
    data: {message: "SMS eșuat către {{ trigger.event.data.phone }}"}
```
