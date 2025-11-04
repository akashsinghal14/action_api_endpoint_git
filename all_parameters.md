## 🔢 NUMERIC MEASUREMENTS
*These measurements require a `unit` parameter (typically "mm")*

### 1. Head Gap
```json
{
  "measurement_type": "head",
  "value": 6,
  "unit": "mm",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 2. Hinge Gap
```json
{
  "measurement_type": "hinge",
  "value": 6,
  "unit": "mm",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 3. Closing Gap
```json
{
  "measurement_type": "closing",
  "value": 6,
  "unit": "mm",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 4. Threshold Gap
```json
{
  "measurement_type": "threshold",
  "value": 5,
  "unit": "mm",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 5. Door Thickness
```json
{
  "measurement_type": "doorthick",
  "value": 60,
  "unit": "mm",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 6. Frame Depth
```json
{
  "measurement_type": "framedepth",
  "value": 300,
  "unit": "mm",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 7. Door Size
```json
{
  "measurement_type": "doorsize",
  "value": 510,
  "unit": "mm",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

---

## ✅ BOOLEAN MEASUREMENTS
*These measurements use "yes"/"no" values and don't require a `unit` parameter*

### 1. Intumescent Strips
```json
{
  "measurement_type": "intustrips",
  "value": "no",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 2. Self-Closing Device
```json
{
  "measurement_type": "selfclosing",
  "value": "no",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 3. Keep Shut Sign
```json
{
  "measurement_type": "shutsign",
  "value": "no",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 4. Hold Open Device
```json
{
  "measurement_type": "holddevice",
  "value": "no",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 5. Certification Visible
```json
{
  "measurement_type": "certivisible",
  "value": "no",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 6. Contains Glazing
```json
{
  "measurement_type": "glazing",
  "value": "no",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 7. Pyro Glazing
```json
{
  "measurement_type": "pyroglazing",
  "value": "no",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 8. Door Close Fully
```json
{
  "measurement_type": "doorclosefully",
  "value": "no",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

### 9. Hinges Fire Rated
```json
{
  "measurement_type": "hingesfirerated",
  "value": "no",
  "api_key": "openai_key",
  "ai_provider": "openai"
}
```

---

## 🧠 CLAUDE AI PROVIDER EXAMPLES

### Numeric Measurement (Claude)
##Replace openai_key with claude_key and openai with claude as below

```json
{
  "measurement_type": "head",
  "value": 6,
  "unit": "mm",
  "api_key": "claude_key",
  "ai_provider": "claude"
}
```

### Boolean Measurement (Claude)
```json
{
  "measurement_type": "hingesfirerated",
  "value": "no",
  "api_key": "claude_key",
  "ai_provider": "claude"
}
```