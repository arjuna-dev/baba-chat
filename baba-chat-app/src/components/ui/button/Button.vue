<template>
  <button :class="buttonClasses" :type="type">
    <slot />
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from 'src/lib/utils';

defineOptions({
  name: 'ShadcnButton',
});

const buttonVariants = cva('dc-button', {
  variants: {
    variant: {
      default: 'dc-button--default',
      secondary: 'dc-button--secondary',
      ghost: 'dc-button--ghost',
      outline: 'dc-button--outline',
      destructive: 'dc-button--destructive',
    },
    size: {
      default: 'dc-button--size-default',
      sm: 'dc-button--size-sm',
      icon: 'dc-button--size-icon',
    },
  },
  defaultVariants: {
    variant: 'default',
    size: 'default',
  },
});

type ButtonVariants = VariantProps<typeof buttonVariants>;

const props = withDefaults(
  defineProps<{
    variant?: ButtonVariants['variant'];
    size?: ButtonVariants['size'];
    class?: string;
    type?: 'button' | 'submit' | 'reset';
  }>(),
  {
    variant: 'default',
    size: 'default',
    class: '',
    type: 'button',
  }
);

const buttonClasses = computed(() =>
  cn(buttonVariants({ variant: props.variant, size: props.size }), props.class)
);
</script>
