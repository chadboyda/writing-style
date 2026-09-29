# Vendored libraries

## proseweave

`proseweave/` is a pinned copy of the proseweave package (cohesion,
readability and easability measures; standard library only). The commit it
came from is in `PROSEWEAVE_VERSION`; its licence and data notices are
`LICENSE.proseweave` and `NOTICE.proseweave`.

It is bundled so the skill works for anyone who can use this repository, with
nothing to install and no access needed to the proseweave repository itself.
`scripts/weave.py` is the entry point.

Do not edit the copy here. Change proseweave in its own repository, commit
there, then refresh:

```bash
python3 vendor/sync_proseweave.py <proseweave-checkout>          # copy and re-pin
python3 vendor/sync_proseweave.py --check <proseweave-checkout>  # has the copy drifted?
```

`proseweave/data/validation.json` records which properties passed validation.
Validation runs in the proseweave repository; that file arrives here with each
sync and should not be edited in place, so `--check` stays clean.
