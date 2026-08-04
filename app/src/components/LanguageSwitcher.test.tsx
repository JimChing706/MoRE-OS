import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LanguageSwitcher } from './LanguageSwitcher'

const mocks = vi.hoisted(() => {
  let lang = 'en'
  return {
    getLang: () => lang,
    changeLanguage: vi.fn((l: string) => {
      lang = l
    }),
    t: (key: string) => key.replace('language.', '').toUpperCase(),
  }
})

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: mocks.t,
    i18n: {
      get language() {
        return mocks.getLang()
      },
      changeLanguage: mocks.changeLanguage,
    },
  }),
}))

describe('LanguageSwitcher', () => {
  beforeEach(() => {
    mocks.changeLanguage.mockClear()
    mocks.changeLanguage('en')
  })

  it('shows the target language label', () => {
    render(<LanguageSwitcher />)
    expect(screen.getByRole('button', { name: 'ZH' })).toBeInTheDocument()
  })

  it('toggles language on click', () => {
    const { rerender } = render(<LanguageSwitcher />)
    fireEvent.click(screen.getByRole('button', { name: 'ZH' }))
    expect(mocks.changeLanguage).toHaveBeenCalledWith('zh')
    rerender(<LanguageSwitcher />)
    expect(screen.getByRole('button', { name: 'EN' })).toBeInTheDocument()
  })
})
