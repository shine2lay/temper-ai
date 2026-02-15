/**
 * FormBuilder - Generates HTML forms from JSON Schema definitions.
 *
 * Used by the property panel to render editable fields for workflow,
 * stage, agent, and tool configurations. Schemas come from Pydantic
 * models via the Studio API and are resolved through SchemaRegistry.
 *
 * CSS classes expected (defined in studio.css):
 *   .studio-field, .studio-field label, .studio-field.invalid,
 *   .field-error, .studio-repeatable, .studio-repeatable-item,
 *   .studio-repeatable-add, .studio-repeatable-remove,
 *   .studio-fieldset, .studio-fieldset-legend, .studio-fieldset-body,
 *   .studio-checkbox-label
 */

const MAX_REF_DEPTH = 10;

export class FormBuilder {
    /**
     * @param {import('./schema-registry.js').SchemaRegistry} schemaRegistry
     */
    constructor(schemaRegistry) {
        this._registry = schemaRegistry;
    }

    /**
     * Build a form for a given schema and data object.
     * @param {object} schema - Resolved JSON schema (no $refs)
     * @param {object} data - Current data values
     * @param {function} onChange - Callback(path, value) when a field changes
     * @param {string} rootPath - Base path prefix for field names
     * @returns {HTMLElement} form container div
     */
    buildForm(schema, data, onChange, rootPath = '') {
        const container = document.createElement('div');
        container.className = 'studio-form';

        if (!schema || !schema.properties) {
            return container;
        }

        const required = schema.required || [];

        for (const [key, propSchema] of Object.entries(schema.properties)) {
            if (key.startsWith('_')) continue;

            const path = rootPath ? `${rootPath}.${key}` : key;
            const value = data != null ? data[key] : undefined;
            const isRequired = required.includes(key);

            const field = this._buildField(
                key, propSchema, value, path, isRequired, onChange, schema
            );
            if (field) container.appendChild(field);
        }

        return container;
    }

    /**
     * Dispatch to the appropriate builder based on effective type.
     */
    _buildField(key, propSchema, value, path, isRequired, onChange, rootSchema) {
        const resolved = this._resolveSchema(propSchema, rootSchema);
        const type = this._getEffectiveType(resolved, rootSchema);

        if (type === 'string' && resolved.enum) {
            return this._buildSelect(key, resolved, value, path, isRequired, onChange);
        }

        switch (type) {
            case 'string':
                return this._buildTextInput(key, resolved, value, path, isRequired, onChange);
            case 'number':
            case 'integer':
                return this._buildNumberInput(key, resolved, value, path, isRequired, onChange);
            case 'boolean':
                return this._buildCheckbox(key, resolved, value, path, onChange);
            case 'array':
                return this._buildArray(key, resolved, value, path, onChange, rootSchema);
            case 'object':
                return this._buildFieldset(key, resolved, value, path, onChange, rootSchema);
            default:
                return this._buildJsonTextarea(key, resolved, value, path, onChange);
        }
    }

    /**
     * Resolve a schema that may contain $ref, anyOf, oneOf, or allOf
     * into its effective concrete schema.
     */
    _resolveSchema(propSchema, rootSchema, depth = 0) {
        if (!propSchema || typeof propSchema !== 'object') return propSchema;
        if (depth > MAX_REF_DEPTH) return propSchema;

        // Direct $ref
        if (propSchema.$ref) {
            const resolved = this._registry.resolveRef(propSchema.$ref, rootSchema);
            if (resolved) return this._resolveSchema(resolved, rootSchema, depth + 1);
            return propSchema;
        }

        // allOf: merge all sub-schemas into one
        if (propSchema.allOf) {
            return this._mergeAllOf(propSchema, rootSchema, depth);
        }

        // anyOf / oneOf: pick the non-null variant for Optional types
        const unionOptions = propSchema.anyOf || propSchema.oneOf;
        if (unionOptions) {
            return this._resolveUnion(unionOptions, propSchema, rootSchema, depth);
        }

        return propSchema;
    }

    /**
     * Merge allOf sub-schemas into a single combined schema.
     * Pydantic uses allOf for discriminated unions and composed models.
     */
    _mergeAllOf(propSchema, rootSchema, depth) {
        const merged = {};
        for (const sub of propSchema.allOf) {
            const resolved = this._resolveSchema(sub, rootSchema, depth + 1);
            if (!resolved) continue;
            Object.assign(merged, resolved);
            if (resolved.properties) {
                merged.properties = { ...merged.properties, ...resolved.properties };
            }
            if (resolved.required) {
                merged.required = [
                    ...(merged.required || []),
                    ...resolved.required
                ];
            }
        }
        // Preserve title/description from the outer schema
        if (propSchema.title) merged.title = propSchema.title;
        if (propSchema.description) merged.description = propSchema.description;
        return merged;
    }

    /**
     * Resolve anyOf/oneOf unions. For Pydantic Optional[T], this
     * produces [T, {type: "null"}] — we pick the non-null variant.
     * For multi-type unions, return the original schema unchanged.
     */
    _resolveUnion(options, propSchema, rootSchema, depth) {
        const nonNull = options.filter(s => s.type !== 'null');

        if (nonNull.length === 1) {
            const resolved = this._resolveSchema(nonNull[0], rootSchema, depth + 1);
            // Preserve outer schema metadata
            if (propSchema.title && !resolved.title) resolved.title = propSchema.title;
            if (propSchema.description && !resolved.description) {
                resolved.description = propSchema.description;
            }
            if (propSchema.default !== undefined && resolved.default === undefined) {
                resolved.default = propSchema.default;
            }
            return resolved;
        }

        // Multi-type union — cannot simplify further
        return propSchema;
    }

    /**
     * Determine the effective JSON Schema type for a property.
     * Handles $ref, anyOf/oneOf (Optional), allOf, and direct type.
     */
    _getEffectiveType(propSchema, rootSchema, depth = 0) {
        if (!propSchema || depth > MAX_REF_DEPTH) return 'unknown';
        if (propSchema.type) return propSchema.type;
        if (propSchema.enum) return 'string';

        if (propSchema.$ref) {
            const resolved = this._registry.resolveRef(propSchema.$ref, rootSchema);
            return resolved
                ? this._getEffectiveType(resolved, rootSchema, depth + 1)
                : 'unknown';
        }

        if (propSchema.allOf) {
            const merged = this._mergeAllOf(propSchema, rootSchema, depth);
            return this._getEffectiveType(merged, rootSchema, depth + 1);
        }

        const unionOptions = propSchema.anyOf || propSchema.oneOf;
        if (unionOptions) {
            const nonNull = unionOptions.filter(s => s.type !== 'null');
            if (nonNull.length === 1) {
                return this._getEffectiveType(nonNull[0], rootSchema, depth + 1);
            }
            // Multi-type union — cannot determine single type
            return 'unknown';
        }

        if (propSchema.properties) return 'object';
        return 'unknown';
    }

    // --- Individual Field Builders ---

    _buildTextInput(key, schema, value, path, isRequired, onChange) {
        const wrapper = this._createFieldWrapper(key, schema, isRequired, path);
        const input = document.createElement('input');
        input.type = 'text';
        input.value = value ?? schema.default ?? '';
        input.placeholder = schema.description || '';

        if (schema.minLength !== undefined) input.minLength = schema.minLength;
        if (schema.maxLength !== undefined) input.maxLength = schema.maxLength;
        if (schema.pattern) input.pattern = schema.pattern;

        input.addEventListener('change', () => {
            const val = input.value;
            onChange(path, val === '' && !isRequired ? undefined : val);
        });
        wrapper.appendChild(input);
        return wrapper;
    }

    _buildNumberInput(key, schema, value, path, isRequired, onChange) {
        const wrapper = this._createFieldWrapper(key, schema, isRequired, path);
        const input = document.createElement('input');
        input.type = 'number';
        input.value = value ?? schema.default ?? '';

        if (schema.minimum !== undefined) input.min = String(schema.minimum);
        if (schema.maximum !== undefined) input.max = String(schema.maximum);
        if (schema.exclusiveMinimum !== undefined) {
            input.min = String(schema.exclusiveMinimum + 1);
        }
        if (schema.exclusiveMaximum !== undefined) {
            input.max = String(schema.exclusiveMaximum - 1);
        }
        if (schema.multipleOf !== undefined) input.step = String(schema.multipleOf);

        input.addEventListener('change', () => {
            const raw = input.value;
            if (raw === '' && !isRequired) {
                onChange(path, undefined);
            } else {
                const parsed = schema.type === 'integer'
                    ? parseInt(raw, 10) : parseFloat(raw);
                onChange(path, isNaN(parsed) ? undefined : parsed);
            }
        });
        wrapper.appendChild(input);
        return wrapper;
    }

    _buildSelect(key, schema, value, path, isRequired, onChange) {
        const wrapper = this._createFieldWrapper(key, schema, isRequired, path);
        const select = document.createElement('select');

        if (!isRequired) {
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = '-- Select --';
            select.appendChild(placeholder);
        }

        for (const enumVal of schema.enum) {
            const opt = document.createElement('option');
            opt.value = enumVal;
            opt.textContent = enumVal;
            if (enumVal === (value ?? schema.default)) opt.selected = true;
            select.appendChild(opt);
        }

        select.addEventListener('change', () => {
            onChange(path, select.value === '' ? undefined : select.value);
        });
        wrapper.appendChild(select);
        return wrapper;
    }

    _buildCheckbox(key, schema, value, path, onChange) {
        const wrapper = document.createElement('div');
        wrapper.className = 'studio-field';
        wrapper.setAttribute('data-path', path);

        const label = document.createElement('label');
        label.className = 'studio-checkbox-label';
        if (schema.description) label.title = schema.description;

        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = value ?? schema.default ?? false;
        input.addEventListener('change', () => onChange(path, input.checked));

        label.appendChild(input);
        label.appendChild(document.createTextNode(this._formatLabel(key)));
        wrapper.appendChild(label);
        return wrapper;
    }

    _buildArray(key, schema, value, path, onChange, rootSchema) {
        const wrapper = this._createFieldWrapper(key, schema, false, path);
        const container = document.createElement('div');
        container.className = 'studio-repeatable';

        const items = Array.isArray(value) ? [...value] : [];
        const itemSchema = this._resolveArrayItemSchema(schema, rootSchema);
        const isSimple = this._isSimpleArrayItem(itemSchema);

        const renderItems = () => {
            container.innerHTML = '';
            this._renderArrayItems(
                container, items, itemSchema, isSimple,
                path, onChange, rootSchema, renderItems
            );
            this._appendAddButton(container, items, isSimple, path, onChange, renderItems);
        };

        renderItems();
        wrapper.appendChild(container);
        return wrapper;
    }

    /**
     * Resolve the items schema for an array property.
     */
    _resolveArrayItemSchema(schema, rootSchema) {
        if (!schema.items) return { type: 'string' };
        return this._resolveSchema(schema.items, rootSchema);
    }

    /**
     * Check whether array items are simple scalars (string, number, etc).
     */
    _isSimpleArrayItem(itemSchema) {
        if (!itemSchema) return true;
        const type = itemSchema.type;
        return type === 'string' || type === 'number' || type === 'integer';
    }

    /**
     * Render each array item into the repeatable container.
     */
    _renderArrayItems(
        container, items, itemSchema, isSimple,
        path, onChange, rootSchema, renderItems
    ) {
        items.forEach((item, index) => {
            const itemDiv = document.createElement('div');
            itemDiv.className = 'studio-repeatable-item';

            if (isSimple) {
                this._renderSimpleArrayItem(
                    itemDiv, items, item, index, path, onChange
                );
            } else {
                this._renderComplexArrayItem(
                    itemDiv, items, item, index, itemSchema,
                    path, onChange, rootSchema
                );
            }

            this._appendRemoveButton(
                itemDiv, items, index, path, onChange, renderItems
            );
            container.appendChild(itemDiv);
        });
    }

    /**
     * Render a simple scalar array item (string/number input).
     */
    _renderSimpleArrayItem(itemDiv, items, item, index, path, onChange) {
        const input = document.createElement('input');
        input.type = 'text';
        input.value = item ?? '';
        input.addEventListener('change', () => {
            items[index] = input.value;
            onChange(path, [...items]);
        });
        itemDiv.appendChild(input);
    }

    /**
     * Render a complex object array item as a nested form.
     */
    _renderComplexArrayItem(
        itemDiv, items, item, index, itemSchema, path, onChange, rootSchema
    ) {
        if (!itemSchema || !itemSchema.properties) {
            // Fallback: render as JSON textarea
            const textarea = document.createElement('textarea');
            textarea.value = JSON.stringify(item, null, 2);
            textarea.addEventListener('change', () => {
                try {
                    items[index] = JSON.parse(textarea.value);
                    onChange(path, [...items]);
                } catch { /* ignore parse errors until valid */ }
            });
            itemDiv.appendChild(textarea);
            return;
        }

        const form = this.buildForm(
            itemSchema, item,
            (subPath, val) => {
                const field = subPath.split('.').pop();
                if (!items[index] || typeof items[index] !== 'object') {
                    items[index] = {};
                }
                items[index][field] = val;
                onChange(path, [...items]);
            },
            `${path}[${index}]`
        );
        itemDiv.appendChild(form);
    }

    /**
     * Append a remove button to an array item.
     */
    _appendRemoveButton(itemDiv, items, index, path, onChange, renderItems) {
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'studio-repeatable-remove';
        removeBtn.textContent = 'x';
        removeBtn.addEventListener('click', () => {
            items.splice(index, 1);
            onChange(path, [...items]);
            renderItems();
        });
        itemDiv.appendChild(removeBtn);
    }

    /**
     * Append an add-item button at the end of the repeatable container.
     */
    _appendAddButton(container, items, isSimple, path, onChange, renderItems) {
        const addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'studio-repeatable-add';
        addBtn.textContent = '+ Add item';
        addBtn.addEventListener('click', () => {
            items.push(isSimple ? '' : {});
            onChange(path, [...items]);
            renderItems();
        });
        container.appendChild(addBtn);
    }

    _buildFieldset(key, schema, value, path, onChange, rootSchema) {
        const fieldset = document.createElement('div');
        fieldset.className = 'studio-fieldset';
        fieldset.setAttribute('data-path', path);

        const legend = document.createElement('div');
        legend.className = 'studio-fieldset-legend';
        legend.textContent = this._formatLabel(key);
        if (schema.description) legend.title = schema.description;
        legend.addEventListener('click', () => {
            fieldset.classList.toggle('collapsed');
        });
        fieldset.appendChild(legend);

        const body = document.createElement('div');
        body.className = 'studio-fieldset-body';

        const resolved = schema.$ref
            ? this._registry.resolveRef(schema.$ref, rootSchema)
            : schema;

        if (resolved && resolved.properties) {
            const form = this.buildForm(resolved, value || {}, onChange, path);
            body.appendChild(form);
        }

        fieldset.appendChild(body);
        return fieldset;
    }

    _buildJsonTextarea(key, schema, value, path, onChange) {
        const wrapper = this._createFieldWrapper(key, schema, false, path);
        const textarea = document.createElement('textarea');
        textarea.rows = 4;

        if (value !== undefined && value !== null) {
            textarea.value = JSON.stringify(value, null, 2);
        } else {
            textarea.value = '';
        }

        textarea.addEventListener('change', () => {
            const raw = textarea.value.trim();
            if (raw === '') {
                onChange(path, undefined);
                wrapper.classList.remove('invalid');
                this._removeFieldError(wrapper);
                return;
            }
            try {
                const parsed = JSON.parse(raw);
                onChange(path, parsed);
                wrapper.classList.remove('invalid');
                this._removeFieldError(wrapper);
            } catch (err) {
                wrapper.classList.add('invalid');
                this._setFieldErrorDirect(wrapper, 'Invalid JSON');
            }
        });

        wrapper.appendChild(textarea);
        return wrapper;
    }

    // --- Shared Helpers ---

    /**
     * Create a standard field wrapper with label and data-path attribute.
     */
    _createFieldWrapper(key, schema, isRequired, path) {
        const wrapper = document.createElement('div');
        wrapper.className = 'studio-field';
        wrapper.setAttribute('data-path', path);

        const label = document.createElement('label');
        const labelText = this._formatLabel(schema.title || key);
        label.textContent = labelText + (isRequired ? ' *' : '');
        if (schema.description) label.title = schema.description;

        wrapper.appendChild(label);
        return wrapper;
    }

    /**
     * Convert snake_case or camelCase to Title Case for display.
     */
    _formatLabel(key) {
        return key
            .replace(/_/g, ' ')
            .replace(/([a-z])([A-Z])/g, '$1 $2')
            .replace(/\b\w/g, c => c.toUpperCase());
    }

    // --- Validation Error Management ---

    /**
     * Set a validation error on a specific field by its data-path.
     * @param {HTMLElement} container - The form container element
     * @param {string} path - The dot-separated field path
     * @param {string} message - The error message to display
     */
    setFieldError(container, path, message) {
        const field = container.querySelector(`[data-path="${path}"]`);
        if (!field) return;

        field.classList.add('invalid');
        this._setFieldErrorDirect(field, message);
    }

    /**
     * Append or update the error span directly on a wrapper element.
     */
    _setFieldErrorDirect(wrapper, message) {
        let errorSpan = wrapper.querySelector('.field-error');
        if (!errorSpan) {
            errorSpan = document.createElement('span');
            errorSpan.className = 'field-error';
            wrapper.appendChild(errorSpan);
        }
        errorSpan.textContent = message;
    }

    /**
     * Remove an existing error span from a wrapper element.
     */
    _removeFieldError(wrapper) {
        const errorSpan = wrapper.querySelector('.field-error');
        if (errorSpan) errorSpan.remove();
    }

    /**
     * Clear all validation errors within a form container.
     * @param {HTMLElement} container - The form container element
     */
    clearErrors(container) {
        const invalids = container.querySelectorAll('.invalid');
        for (const el of invalids) {
            el.classList.remove('invalid');
        }
        const errors = container.querySelectorAll('.field-error');
        for (const el of errors) {
            el.remove();
        }
    }

    /**
     * Set multiple field errors at once from a validation result.
     * @param {HTMLElement} container - The form container element
     * @param {Array<{path: string, message: string}>} errors - Error list
     */
    setErrors(container, errors) {
        this.clearErrors(container);
        for (const { path, message } of errors) {
            this.setFieldError(container, path, message);
        }
    }
}
