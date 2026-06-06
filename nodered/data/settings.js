module.exports = {
    flowFile: 'flows.json',
    uiPort: process.env.PORT || 1880,
    credentialSecret: process.env.NODE_RED_CREDENTIAL_SECRET || 'change-me-soundtouch-radio',
    contextStorage: {
        default: {
            module: 'localfilesystem'
        },
        memoryOnly: {
            module: 'memory'
        }
    },
    functionExternalModules: false,
    functionGlobalContext: {
        fetch: globalThis.fetch
    },
    editorTheme: {
        projects: {
            enabled: false
        }
    }
}
