# Cook programs

A program is a list of steps separated by `;` or new lines. Each step has actions, then optionally `until` and one
or more conditions joined by `or`. The program runs **on the controller**, so it keeps going if Wi-Fi or Home
Assistant drop (conditions on probes whose data comes through Home Assistant pause while it is unavailable).

```
name: Pork butt
pit 250 until food1 >= 165 for 30m
pit 275 until food1 >= 203
hold 200 notify "Pork is done - rest it"
```

| Actions | |
|---|---|
| `pit N` | set the pit target |
| `hold N` | set the pit target and stay (final step). The stock controller's pit range is 200–700 °F, so the lowest hold is 200 |
| `notify "text"` | send a notification when the step starts |
| `shutdown` | end the program |

| Conditions | |
|---|---|
| `food1 >= N [for 30m]` | probe at or above N (held for a time). Also `<=`. Probes: `pit`, `food1` … `food6` (each slot reads the source chosen for it) |
| `food1 done` | the probe reached its own target |
| `after 2h` / `after 90m` | time spent in this step |
| `at 17:30` | clock time |
| `stall_start food1`, `stall_end food1` | the stall detector's events |

Temperatures use the device unit (°F by default); add `F` or `C` to be explicit (`74C`). A step with no `until`
(and not `hold`) completes immediately, so `notify "Spritz now"` can sit between steps.

**Start the cook on the grill's panel first.** The stock controller ignores new targets while it's idle; the
program keeps retrying every minute and tells you if the grill still hasn't taken its target after a few tries.

**Manual changes:** if the pit target is changed outside the program (dashboard, phone, grill panel), the program
**pauses**; resume it to go back to the program's target. After a controller restart, a running program is restored
**paused** at the same step, and you get a notification.

**Presets** (in `firmware/core.yaml`): Pork shoulder (Texas crutch), Brisket, Ribs, Chicken (hot & fast), Hold warm.
Pick one with **Program preset**, or type your own in **Program**, or ask the AI (`script.smoker_plan_cook`).
