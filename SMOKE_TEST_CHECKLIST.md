# Smoke Test Checklist

Checklist manual de validacion rapida para confirmar que la app sigue operativa despues de cambios o antes de compartir el repo.

## 1. Preparacion

- [ ] Estar en la raiz del repo
- [ ] Tener `.venv` creado
- [ ] Haber corrido `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
- [ ] Si se quiere probar remoto, tener `.streamlit\secrets.toml` configurado

## 2. Arranque

- [ ] Correr `.\.venv\Scripts\python.exe -m streamlit run app.py`
- [ ] Confirmar que abre la UI principal
- [ ] Confirmar que el sidebar carga sin errores visibles

Esperado:

- la app abre sin depender de `PYTHONPATH`
- si no hay datos, el estado vacio sigue siendo usable

## 3. Carga y procesamiento local

- [ ] Subir al menos un archivo valido de TeamBuildr o evaluaciones
- [ ] Ejecutar el flujo de procesamiento principal
- [ ] Confirmar que aparecen filas, metricas o tablas asociadas

Esperado:

- el dataset se procesa sin error silencioso
- el estado local se actualiza

## 4. Dashboard y paginas

- [ ] Revisar el dashboard principal
- [ ] Abrir `01_load_monitoring`
- [ ] Abrir `02_jump_evaluation`
- [ ] Abrir `03_athlete_profile`
- [ ] Abrir `04_team_dashboard`
- [ ] Abrir `05_reports`

Esperado:

- las paginas abren
- no hay errores visibles de estado o columnas faltantes

## 5. Gestion de historial local

- [ ] Abrir `06_history_manager`
- [ ] Cambiar de dataset
- [ ] Probar filtros
- [ ] Descargar CSV filtrado
- [ ] Probar `Borrar filas filtradas` sobre un dataset de prueba
- [ ] Probar `Vaciar dataset local` sobre un dataset de prueba

Esperado:

- antes de la accion destructiva se genera backup
- aparece confirmacion explicita
- `Vaciar dataset local` deja el dataset en 0 filas
- el mensaje de exito y backup sigue visible tras el rerun

## 6. Exportes

- [ ] Probar exportacion Excel
- [ ] Si el entorno lo permite, probar exportacion visual/PDF

Esperado:

- Excel se genera
- las exportaciones visuales no fallan por la combinacion `plotly` / `kaleido`

## 7. Modo local vs remoto

### Sin Supabase configurado

- [ ] Confirmar que la UI explica que la app sigue funcionando localmente
- [ ] Confirmar que no promete sincronizacion remota

### Con Supabase configurado

- [ ] Probar `Publicar local -> Supabase`
- [ ] Probar `Reemplazar local <- Supabase`

Esperado:

- el comportamiento visible coincide con el dataset seleccionado
- no hay confusion entre local y remoto

## 8. Validacion automatica recomendada

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_phase1_reporting tests.test_phase2_history tests.test_phase3_remote_store
```

## 9. Criterio de aprobado

Considerar el smoke test aprobado si:

- la app arranca
- los flujos principales locales funcionan
- historial local responde como se espera
- las exportaciones basicas funcionan
- no aparecen errores visibles en UI en los recorridos principales
