# Publishing to iRODS

## Playbook

Main Options

|         | Python stack                                                        | Perl stack                                      |
| ------- | ------------------------------------------------------------------- | ----------------------------------------------- |
| Script  | Option A<br><br>`publish-directory` utility from `npg-irods-python` | Option C<br><br>`npg_publish_tree.py`           |
| Library | Option B<br><br>Build on top of `partisan`                          | Option D<br><br>Build on top of `TreePublisher` |


### Option A: `publish-directory` utility from `npg-irods-python`

Good for...

- Simpler requirements around permissions
- Calling from outside a Python application

### Option B: Build on top of `partisan` library

Good for...

- More complex requirements around permissions
- Calling from within a Python application

How to use....

- One call per set of common permissions
- Select scope using `--exclude`, `--include` (1) and `--max-depth` (1)

(1) To be implemented

### Option C: `npg_publish_tree.py`

Maintaining existing implementations that already use this approach

### Option D: Build on top of `TreePublisher`

Maintaining existing implementations that already use this approach

## Comparison

|                           | npg_publish_tree.pl                                                                                                                                                                     | publish-directory                                                                                                                                                                                           | Notes                                                                                                   |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Different, significant    |                                                                                                                                                                                         |                                                                                                                                                                                                             |                                                                                                         |
| ... Include               | `--include` flag<br><br>Use cases include:<br>RVI Wrapper<br>npg-seq-pipeline (Illumina)                                                                                                | ==Not supported==                                                                                                                                                                                           |                                                                                                         |
| ... Exclude               | `--exclude` flag<br>Perl Reg Ex<br><br>Paths relative or absolute depending on whether source directory below working directory<br><br>Uses `=~`. Looking for match anywhere in string. | `--exclude` flag<br>Python Reg Ex<br><br>Uses `.match`. Looks for match from start of string.                                                                                                               | ==Different, significant==<br><br>(Also any Perl/Python re differences)<br><br>08/09/2025 Marco strict? |
| ...Failure handling       | `--max-errors N` flag<br><br>Default behaviour to abort on > 0 errors<br><br>Use cases include:<br>npg_10x_wrappers                                                                     | No flag/customisation<br><br>==Handle exceptions and report on number of errors==                                                                                                                           | ==Different, significant==                                                                              |
| Different, not signficant |                                                                                                                                                                                         |                                                                                                                                                                                                             |                                                                                                         |
| ... Collection            | `--collection` flag<br><br>Doesn't require parent collection to exist                                                                                                                   | `collection` positional arg<br><br>Require parent collection to exist                                                                                                                                       | Different, not significant                                                                              |
| ... Logging               | `--logconf`<br>log4perl                                                                                                                                                                 | `--log-config`                                                                                                                                                                                              | Different, not significant                                                                              |
| ... Retry mechanism       | Restart file mechanism<br><br>`--restart{-,_}file`<br><br>Whilst used by scripts built on HTS::TreePublisher, not used by users of npg_tree_publish?                                    | Fill mechanism<br><br>`--fill`<br><br>Fills missing data objects and those with mismatched checksums<br><br>Allows you to restart after failure. Use of checksums means superior to restart file mechanism. | Different, not significant<br><br>08/09/2025 Marco not used restart file. Ask Jaime.                    |
| ... Source directory      | Used: `--source` flag<br><br>Also: `--source{-,_}directory`                                                                                                                             | `directory` positional arg                                                                                                                                                                                  | Different, not significant                                                                              |
| ... Verbosity             | `--verbose`<br>Print messages while processing                                                                                                                                          | `--verbose`<br>Controls logging level<br>Enable INFO level                                                                                                                                                  | Different, not significant                                                                              |
| Same                      |                                                                                                                                                                                         |                                                                                                                                                                                                             |                                                                                                         |
| ... Force update          | `--force` flag                                                                                                                                                                          | Same                                                                                                                                                                                                        | Same                                                                                                    |
| ... Group                 | `--group` flag                                                                                                                                                                          | Same                                                                                                                                                                                                        | Same                                                                                                    |
| ... Metadata              | `--metadata`<br><br>JSON file in baton syntax<br>An array of AVUs                                                                                                                       | `--metadata-file`<br><br>Same                                                                                                                                                                               |                                                                                                         |
| Other                     |                                                                                                                                                                                         |                                                                                                                                                                                                             |                                                                                                         |
| Test coverage             | Used extensively                                                                                                                                                                        | Not used?<br><br>How comprehensively tested?<br><br>==???==                                                                                                                                                 | ==??==                                                                                                  |
