import {brandDefault} from './default';
import type {Brand} from './types';

// Реєстр брендів. Додав бренд сюди — і він автоматично зʼявився у випадайці
// `brand` кожної композиції (zod-enum читає саме звідси).
//
// Як додати свій:
//   1. скопіюй `default.ts` під своєю назвою, напр. `moye.ts`;
//   2. поміняй у ньому кольори та шрифти;
//   3. імпортуй сюди й додай у BRANDS.
export const BRANDS = {
  default: brandDefault,
} as const;

export type BrandId = keyof typeof BRANDS;

export const brandIds = Object.keys(BRANDS) as [BrandId, ...BrandId[]];

export const getBrand = (id: BrandId): Brand => BRANDS[id];

export type {Brand} from './types';
