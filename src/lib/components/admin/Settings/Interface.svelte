<script lang="ts">
	import { getModels, getTaskConfig, updateTaskConfig } from '$lib/apis';
	import { config, settings } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getBaseModels } from '$lib/apis/models';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	let taskConfig = {
		TASK_MODEL: '',
		TASK_MODEL_EXTERNAL: '',
		ENABLE_TITLE_GENERATION: true,
		TITLE_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_FOLLOW_UP_GENERATION: true,
		FOLLOW_UP_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_SUGGEST_GENERATION: true,
		SUGGEST_GENERATION_COUNT: 3,
		SUGGEST_GENERATION_MODE: 'literal',
		SUGGEST_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_QUERY_REWRITING: false,
		QUERY_REWRITING_MODEL: '',
		QUERY_REWRITING_PROMPT_TEMPLATE: '',
		MEMCHAT_EMBED_CONNECTION_IDX: 0,
		MEMCHAT_EMBED_MODEL: 'text-embedding-bge-base-en-v1.5',
		OPENAI_CONNECTIONS: [],
		IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_AUTOCOMPLETE_GENERATION: true,
		AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH: -1,
		TAGS_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_TAGS_GENERATION: true,
		ENABLE_SEARCH_QUERY_GENERATION: true,
		ENABLE_RETRIEVAL_QUERY_GENERATION: true,
		QUERY_GENERATION_PROMPT_TEMPLATE: '',
		TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE: '',
		VOICE_MODE_PROMPT_TEMPLATE: ''
	};

	const updateInterfaceHandler = async () => {
		taskConfig = await updateTaskConfig(localStorage.token, taskConfig);
	};

	let workspaceModels = null;
	let baseModels = null;

	let models = null;

	const init = async () => {
		try {
			taskConfig = await getTaskConfig(localStorage.token);

			workspaceModels = await getBaseModels(localStorage.token);
			baseModels = await getModels(localStorage.token, null, false);

			models = baseModels.map((m) => {
				const workspaceModel = workspaceModels.find((wm) => wm.id === m.id);

				if (workspaceModel) {
					return {
						...m,
						...workspaceModel
					};
				} else {
					return {
						...m,
						id: m.id,
						name: m.name,

						is_active: true
					};
				}
			});

			console.debug('models', models);
		} catch (err) {
			console.error('Failed to initialize Interface settings:', err);
			toast.error(err?.detail ?? err?.message ?? $i18n.t('Failed to load Interface settings'));
			models = [];
		}
	};

	onMount(async () => {
		await init();
	});
</script>

{#if models !== null && taskConfig}
	<form
		class="flex flex-col h-full justify-between space-y-3 text-sm"
		on:submit|preventDefault={() => {
			updateInterfaceHandler();
			dispatch('save');
		}}
	>
		<div class="  overflow-y-scroll scrollbar-hidden h-full pr-1.5">
			<div class="mb-3.5">
				<div class=" mt-0.5 mb-2.5 text-base font-medium">{$i18n.t('Tasks')}</div>

				<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

				<div class=" mb-2 font-medium flex items-center">
					<div class=" text-xs mr-1">{$i18n.t('Task Model')}</div>
					<Tooltip
						content={$i18n.t(
							'A task model is used when performing tasks such as generating titles for chats and web search queries'
						)}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="size-3.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z"
							/>
						</svg>
					</Tooltip>
				</div>

				<div class=" mb-2.5 flex w-full gap-2">
					<div class="flex-1">
						<div class=" text-xs mb-1">{$i18n.t('Local Task Model')}</div>
						<select
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={taskConfig.TASK_MODEL}
							placeholder={$i18n.t('Select a model')}
							on:change={() => {
								if (taskConfig.TASK_MODEL) {
									const model = models.find((m) => m.id === taskConfig.TASK_MODEL);
									if (model) {
										if (
											model?.access_grants &&
											!model.access_grants.some(
												(g) =>
													g.principal_type === 'user' &&
													g.principal_id === '*' &&
													g.permission === 'read'
											)
										) {
											toast.error(
												$i18n.t(
													'This model is not publicly available. Please select another model.'
												)
											);
										}

										taskConfig.TASK_MODEL = model.id;
									} else {
										taskConfig.TASK_MODEL = '';
									}
								}
							}}
						>
							<option value="" selected>{$i18n.t('Current Model')}</option>
							{#each models as model}
								<option value={model.id} class="bg-gray-100 dark:bg-gray-700">
									{model.name}
									{model?.connection_type === 'local' ? `(${$i18n.t('Local')})` : ''}
								</option>
							{/each}
						</select>
					</div>

					<div class="flex-1">
						<div class=" text-xs mb-1">{$i18n.t('External Task Model')}</div>
						<select
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={taskConfig.TASK_MODEL_EXTERNAL}
							placeholder={$i18n.t('Select a model')}
							on:change={() => {
								if (taskConfig.TASK_MODEL_EXTERNAL) {
									const model = models.find((m) => m.id === taskConfig.TASK_MODEL_EXTERNAL);
									if (model) {
										if (
											model?.access_grants &&
											!model.access_grants.some(
												(g) =>
													g.principal_type === 'user' &&
													g.principal_id === '*' &&
													g.permission === 'read'
											)
										) {
											toast.error(
												$i18n.t(
													'This model is not publicly available. Please select another model.'
												)
											);
										}

										taskConfig.TASK_MODEL_EXTERNAL = model.id;
									} else {
										taskConfig.TASK_MODEL_EXTERNAL = '';
									}
								}
							}}
						>
							<option value="" selected>{$i18n.t('Current Model')}</option>
							{#each models as model}
								<option value={model.id} class="bg-gray-100 dark:bg-gray-700">
									{model.name}
									{model?.connection_type === 'local' ? `(${$i18n.t('Local')})` : ''}
								</option>
							{/each}
						</select>
					</div>
				</div>

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Title Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_TITLE_GENERATION} />
				</div>

				{#if taskConfig.ENABLE_TITLE_GENERATION}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Title Generation Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.TITLE_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Voice Mode Custom Prompt')}
					</div>

					<Switch
						state={taskConfig.VOICE_MODE_PROMPT_TEMPLATE != null}
						on:change={(e) => {
							if (e.detail) {
								taskConfig.VOICE_MODE_PROMPT_TEMPLATE = '';
							} else {
								taskConfig.VOICE_MODE_PROMPT_TEMPLATE = null;
							}
						}}
					/>
				</div>

				{#if taskConfig.VOICE_MODE_PROMPT_TEMPLATE != null}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Voice Mode Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.VOICE_MODE_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Follow Up Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_FOLLOW_UP_GENERATION} />
				</div>

				{#if taskConfig.ENABLE_FOLLOW_UP_GENERATION}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Follow Up Generation Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.FOLLOW_UP_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Suggest Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_SUGGEST_GENERATION} />
				</div>

				{#if taskConfig.ENABLE_SUGGEST_GENERATION}
					<div class="mb-2.5 flex w-full items-center justify-between">
						<div class="self-center text-xs font-medium">{$i18n.t('Suggestion Count')}</div>
						<div class="flex items-center gap-2">
							{#each [1, 2, 3] as n}
								<button
									type="button"
									class="px-2 py-0.5 text-xs rounded-lg border {taskConfig.SUGGEST_GENERATION_COUNT === n
										? 'bg-gray-100 dark:bg-gray-700 font-semibold'
										: 'border-transparent'}"
									on:click={() => (taskConfig.SUGGEST_GENERATION_COUNT = n)}
								>
									{n}
								</button>
							{/each}
						</div>
					</div>

					<div class="mb-2.5 flex w-full items-center justify-between">
						<div class="self-center text-xs font-medium">{$i18n.t('Suggestion Mode')}</div>
						<div class="flex items-center gap-2">
							{#each ['literal', 'inspire'] as m}
								<button
									type="button"
									class="px-2 py-0.5 text-xs rounded-lg border {taskConfig.SUGGEST_GENERATION_MODE === m
										? 'bg-gray-100 dark:bg-gray-700 font-semibold'
										: 'border-transparent'}"
									on:click={() => {
										taskConfig.SUGGEST_GENERATION_MODE = m;
										if (taskConfig.SUGGEST_GENERATION_PROMPT_TEMPLATE === '') {
											taskConfig.SUGGEST_GENERATION_PROMPT_TEMPLATE = '';
										}
									}}
								>
									{m}
								</button>
							{/each}
						</div>
					</div>

					<div class="mb-2.5">
						<div class="mb-1 text-xs font-medium">{$i18n.t('Suggest Generation Prompt')}</div>
						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt for the selected mode, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.SUGGEST_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt for the selected mode, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium flex items-center gap-1">
						{$i18n.t('Query Rewriting')}
						<Tooltip
							content={$i18n.t(
								'Before searching memories, rewrite the user\'s message into a short semantic search query focused on concepts rather than literal words'
							)}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="size-3.5"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z"
								/>
							</svg>
						</Tooltip>
					</div>

					<Switch bind:state={taskConfig.ENABLE_QUERY_REWRITING} />
				</div>

				{#if taskConfig.ENABLE_QUERY_REWRITING}
					<div class="mb-2.5">
						<div class=" text-xs mb-1">{$i18n.t('Query Rewriting Model')}</div>
						<select
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={taskConfig.QUERY_REWRITING_MODEL}
							on:change={() => {
								if (taskConfig.QUERY_REWRITING_MODEL) {
									const model = models.find((m) => m.id === taskConfig.QUERY_REWRITING_MODEL);
									if (model) {
										if (
											model?.access_grants &&
											!model.access_grants.some(
												(g) =>
													g.principal_type === 'user' &&
													g.principal_id === '*' &&
													g.permission === 'read'
											)
										) {
											toast.error(
												$i18n.t(
													'This model is not publicly available. Please select another model.'
												)
											);
										}
										taskConfig.QUERY_REWRITING_MODEL = model.id;
									} else {
										taskConfig.QUERY_REWRITING_MODEL = '';
									}
								}
							}}
						>
							<option value="" selected>{$i18n.t('Task Model (default)')}</option>
							{#each models as model}
								<option value={model.id} class="bg-gray-100 dark:bg-gray-700">
									{model.name}
									{model?.connection_type === 'local' ? `(${$i18n.t('Local')})` : ''}
								</option>
							{/each}
						</select>
					</div>

					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Query Rewriting Prompt')}</div>
						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						>
							<Textarea
								bind:value={taskConfig.QUERY_REWRITING_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

				<div class="mb-1 text-xs font-medium flex items-center gap-1">
					{$i18n.t('Memory Embedding')}
					<Tooltip
						content={$i18n.t('OpenAI-compatible embedding service used for memory search and storage.')}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="size-3.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z"
							/>
						</svg>
					</Tooltip>
				</div>

				<div class="mb-2.5">
					<div class="text-xs mb-1">{$i18n.t('Embedding Connection')}</div>
					<select
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						bind:value={taskConfig.MEMCHAT_EMBED_CONNECTION_IDX}
					>
						{#each taskConfig.OPENAI_CONNECTIONS as conn}
							<option value={conn.idx}>{conn.url}</option>
						{/each}
					</select>
				</div>

				<div class="mb-2.5">
					<div class="text-xs mb-1 flex items-center gap-1">
						{$i18n.t('Embedding Model')}
						<Tooltip
							content={$i18n.t(
								'⚠️ Changing the embedding model is incompatible with existing memory data. All stored memories were embedded with the current model — switching will break semantic search until memories are re-embedded.'
							)}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="size-3.5 text-yellow-500"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
								/>
							</svg>
						</Tooltip>
					</div>
					<input
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						type="text"
						bind:value={taskConfig.MEMCHAT_EMBED_MODEL}
						placeholder="text-embedding-bge-base-en-v1.5"
					/>
					<div class="mt-1 text-xs text-yellow-600 dark:text-yellow-400">
						{$i18n.t('⚠️ Changing this model is incompatible with existing memory data.')}
					</div>
				</div>

				<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2" />

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Tags Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_TAGS_GENERATION} />
				</div>

				{#if taskConfig.ENABLE_TAGS_GENERATION}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">{$i18n.t('Tags Generation Prompt')}</div>

						<Tooltip
							content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placement="top-start"
						>
							<Textarea
								bind:value={taskConfig.TAGS_GENERATION_PROMPT_TEMPLATE}
								placeholder={$i18n.t(
									'Leave empty to use the default prompt, or enter a custom prompt'
								)}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Retrieval Query Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_RETRIEVAL_QUERY_GENERATION} />
				</div>

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Web Search Query Generation')}
					</div>

					<Switch bind:state={taskConfig.ENABLE_SEARCH_QUERY_GENERATION} />
				</div>

				<div class="mb-2.5">
					<div class=" mb-1 text-xs font-medium">{$i18n.t('Query Generation Prompt')}</div>

					<Tooltip
						content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						placement="top-start"
					>
						<Textarea
							bind:value={taskConfig.QUERY_GENERATION_PROMPT_TEMPLATE}
							placeholder={$i18n.t(
								'Leave empty to use the default prompt, or enter a custom prompt'
							)}
						/>
					</Tooltip>
				</div>

				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class=" self-center text-xs font-medium">
						{$i18n.t('Autocomplete Generation')}
					</div>

					<Tooltip content={$i18n.t('Enable autocomplete generation for chat messages')}>
						<Switch bind:state={taskConfig.ENABLE_AUTOCOMPLETE_GENERATION} />
					</Tooltip>
				</div>

				{#if taskConfig.ENABLE_AUTOCOMPLETE_GENERATION}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">
							{$i18n.t('Autocomplete Generation Input Max Length')}
						</div>

						<Tooltip
							content={$i18n.t('Character limit for autocomplete generation input')}
							placement="top-start"
						>
							<input
								class="w-full outline-hidden bg-transparent"
								bind:value={taskConfig.AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH}
								placeholder={$i18n.t('-1 for no limit, or a positive integer for a specific limit')}
							/>
						</Tooltip>
					</div>
				{/if}

				<div class="mb-2.5">
					<div class=" mb-1 text-xs font-medium">{$i18n.t('Image Prompt Generation Prompt')}</div>

					<Tooltip
						content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						placement="top-start"
					>
						<Textarea
							bind:value={taskConfig.IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE}
							placeholder={$i18n.t(
								'Leave empty to use the default prompt, or enter a custom prompt'
							)}
						/>
					</Tooltip>
				</div>

				<div class="mb-2.5">
					<div class=" mb-1 text-xs font-medium">{$i18n.t('Tools Function Calling Prompt')}</div>

					<Tooltip
						content={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
						placement="top-start"
					>
						<Textarea
							bind:value={taskConfig.TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE}
							placeholder={$i18n.t(
								'Leave empty to use the default prompt, or enter a custom prompt'
							)}
						/>
					</Tooltip>
				</div>
			</div>
		</div>

		<div class="flex justify-end text-sm font-medium">
			<button
				class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
				type="submit"
			>
				{$i18n.t('Save')}
			</button>
		</div>
	</form>
{:else}
	<div class=" h-full w-full flex justify-center items-center">
		<Spinner className="size-5" />
	</div>
{/if}
