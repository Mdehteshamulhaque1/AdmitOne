## Summary

<!-- What does this change do and why? Keep it to 1–2 sentences. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Security fix
- [ ] Refactor / no behavior change
- [ ] Docs / CI / infrastructure

## Security & tenant isolation checklist

- [ ] Every organization-owned query is organization-scoped
- [ ] No authorization bypass introduced (server-side enforcement unchanged)
- [ ] No secrets added to code, responses, logs, or audit details
- [ ] Visitor lifecycle transitions still happen in `visits/services.py`
- [ ] (If touched) QR pass signing/organization-bound contract unchanged

## Verification

- [ ] `python manage.py test` passes (backend)
- [ ] `python manage.py test e2e_smoke` passes
- [ ] `npm run build` passes (frontend)
- [ ] `python manage.py check --deploy` clean with `DJANGO_ENV=production`
- [ ] Added/extended tests for the fixed behaviour (tests fail before, pass after)

## Files changed

<!-- Link the key files here -->

## Notes for reviewers

<!-- Anything unusual, migration requirements, or follow-up work -->