/**
 * SchemaRegistry - Fetches and caches JSON Schemas from the Studio API.
 */
export class SchemaRegistry {
    constructor() {
        this._cache = new Map();
    }

    /**
     * Fetch a JSON Schema for a config type.
     * @param {string} configType - 'workflows' | 'stages' | 'agents' | 'tools'
     * @returns {Promise<object>} The JSON Schema
     */
    async getSchema(configType) {
        if (this._cache.has(configType)) {
            return this._cache.get(configType);
        }
        const resp = await fetch(`/api/studio/schemas/${configType}`);
        if (!resp.ok) {
            throw new Error(`Failed to fetch schema for ${configType}: ${resp.status}`);
        }
        const schema = await resp.json();
        this._cache.set(configType, schema);
        return schema;
    }

    clearCache() {
        this._cache.clear();
    }

    /**
     * Get the inner schema (e.g., WorkflowConfigInner from WorkflowConfig).
     * Maps config type to its wrapper property:
     *   workflows -> .workflow, stages -> .stage, agents -> .agent, tools -> .tool
     */
    getInnerSchema(configType, fullSchema) {
        if (!fullSchema || !fullSchema.properties) return null;

        // workflows -> workflow, stages -> stage, etc.
        const propName = configType.endsWith('s') ? configType.slice(0, -1) : configType;
        const prop = fullSchema.properties[propName];
        if (!prop) return null;

        if (prop.$ref) {
            return this.resolveRef(prop.$ref, fullSchema);
        }

        // Handle allOf wrapping
        if (prop.allOf) {
            const ref = prop.allOf.find(item => item.$ref);
            if (ref) return this.resolveRef(ref.$ref, fullSchema);
        }

        return prop;
    }

    /**
     * Resolve a $ref within a schema.
     * Handles "#/$defs/ModelName" and "#/definitions/ModelName" references.
     */
    resolveRef(ref, rootSchema) {
        if (!ref || typeof ref !== 'string' || !ref.startsWith('#/')) {
            return null;
        }
        const parts = ref.replace('#/', '').split('/');
        let current = rootSchema;
        for (const part of parts) {
            if (!current || typeof current !== 'object') return null;
            current = current[part];
        }
        return current || null;
    }

    /**
     * Resolve all $ref pointers in a schema to produce a self-contained schema.
     * Guards against circular references with a visited set.
     */
    resolveAllRefs(schema, rootSchema, visited = new Set()) {
        if (!schema || typeof schema !== 'object') return schema;

        if (schema.$ref) {
            if (visited.has(schema.$ref)) {
                return { type: 'object', description: 'Circular reference' };
            }
            // Clone visited so sibling branches can resolve the same $ref independently
            const branchVisited = new Set(visited);
            branchVisited.add(schema.$ref);
            const resolved = this.resolveRef(schema.$ref, rootSchema);
            if (resolved) return this.resolveAllRefs(resolved, rootSchema, branchVisited);
            return schema;
        }

        if (Array.isArray(schema)) {
            return schema.map(item => this.resolveAllRefs(item, rootSchema, new Set(visited)));
        }

        const result = {};
        for (const [key, value] of Object.entries(schema)) {
            result[key] = this.resolveAllRefs(value, rootSchema, new Set(visited));
        }
        return result;
    }

    /**
     * Get required field names from a schema.
     */
    getRequiredFields(schema) {
        return (schema && schema.required) ? schema.required : [];
    }

    /**
     * Determine the effective type of a schema property.
     */
    getPropertyType(property, rootSchema) {
        if (!property) return 'unknown';
        if (property.type) return property.type;

        if (property.$ref) {
            const resolved = this.resolveRef(property.$ref, rootSchema);
            return this.getPropertyType(resolved, rootSchema);
        }

        const options = property.anyOf || property.oneOf;
        if (options) {
            // Filter out null type for Optional fields
            const nonNull = options.filter(o => o.type !== 'null');
            if (nonNull.length === 1) return this.getPropertyType(nonNull[0], rootSchema);
            return nonNull.map(o => this.getPropertyType(o, rootSchema)).join(' | ');
        }

        return 'object';
    }
}
