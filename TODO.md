* Find a simple solution to automatically populate a world with the baselines when a path is specified and have a symlink pointing to the baseline(s?) in the file system

* Remove baseline providers and move baseline logic to caches
* Allow `None` (and maybe even empty collections) as default value and omit it in the json representation

* Implement lazy inflation of balloon fields, with possibility to eagerly inflate all of them at provision time
* Implement flat vs nested database structure, with the latter supporting class qualname collisions thanks to conformity to python module structure

* Support multiple baselines for a single world
