# How the cook-time prediction works

Per food probe, on the controller (no network needed), recalculated every minute.

1. **Model.** Core temperature follows `dT/dt = k · (T_pit − T)` while warming and finishing, with an evaporative
   **stall** in between (a plateau around 150–170 °F). `k` is the heating coefficient: smaller for bigger cuts.
2. **Starting point: similar past cooks.** Every finished cook is saved on the controller (up to 40): protein,
   weight, pit temperature, outdoor temperature/humidity/wind, wrapped, fitted `k` before and after the stall,
   stall length, total time. A new cook's assumptions are a similarity-weighted average of past cooks, each scaled
   to the new weight and pit temperature (heating time ∝ weight^⅔). With no history, per-protein defaults are used,
   scaled by weight and corrected by a **grill heat factor** learned from all past cooks.
3. **Live fitting.** As data arrives, `k` is fitted from the probe's own curve (weighted least squares with a
   one-hour memory), separately before and after the stall. The more similar past cooks there are, the longer the
   prior holds against noisy early data.
4. **Stall.** Detected when the probe is between ~135 and 180 °F, has risen at least 18 °F since the start, and
   rises less than 3 °F/h for 20 minutes; over when it rises faster than 6 °F/h for 10 minutes. Its expected length
   comes from past cooks, adjusted for pit temperature, how fast this cook heated, humidity (dry air → longer) and
   wrapping (shorter, and "wrapped during the stall" ends it within ~45 min).
5. **Forecast.** The model is simulated forward minute by minute using the pit temperature the **cook program**
   will set at each step (so "250 until 165, then 275" is accounted for), and the temperature the pit is
   **actually holding** (if it runs 20 °F under target on a cold windy day, that's what's used). Optimistic and
   pessimistic runs give the range.
6. **Whole-cook estimate** (before the probe is in): the same simulation from fridge temperature, which feeds the
   "light the grill by" time for a serve-by time.

Tested against a separate two-node heat model with a realistic stall (`tests/test_core.cpp`): mean error ~10 % of
cook time on a first cook with no history, improving with history; the pre-cook estimate was within ~5 % of a
14 h cook after one similar cook.

The Home Assistant AI advisor gives an independent second opinion every 30 minutes; it is shown alongside, never
used to control anything.
