# profiles/

Layer-role profiles, one per client (or per client drafting standard). Create one with

```bash
c2b profile suggest client.dxf -o profiles/client-x.yaml
```

then edit the roles that were guessed with `low`/`none` confidence and pass the file to
`c2b extract -p profiles/client-x.yaml`. See `docs/profiles.md` for the role and
tolerance reference. `example-aia-layers.yaml` is the auto-suggestion for an AIA-style
layer set (`S-COLS`, `S-BEAM-IDEN`, `S-FND`, ...).
