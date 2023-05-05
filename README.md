# IntegrationMinimal

A minimal version of the code necessary to facilitate various features available in Steam. The intention here is to apply this in a GOG Galaxy plugin, but for development and testing, it is separated here.

## Reasoning:

The plugin broken in early March, when Steam changed their authentication workflow. The code in the plugin is unnecessarily complicated and difficult to work with, in addition to being poorly organized. This version attempts to streamline the program while also adding documentation for readibility and future maintainability. 

## Why not ValvePython?

ValvePython is fantastic, and a lot of the original code was a jury-rigged version of it. But the way our python packages are deployed in Galaxy as a plugin, every dependency we use needs to be installed in the plugin file. We're only using a very specific subset of ValvePython, but in order to get it, we'd need basically all of it, and all the dependencies it uses need to be added as well. This makes our plugin larger, which we don't want. In the end, we may end up using valvepython anyway and just eating this cost, but for now we're trying to avoid that.

### Design

The code here is run via the command line. Important features necessary for actually using this as a plugin such as a cache to store friends, achievements, owned games, etc, are all omitted. The goal here is to literally get the authentication working and retrieve a refresh and access token.