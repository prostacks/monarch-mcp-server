"""GraphQL query and mutation constants for the Monarch Money MCP Server.

All custom GraphQL operations that extend beyond what the monarchmoney library
provides are defined here. These were discovered via live API probing and HAR
analysis of the Monarch web app (April 2026).
"""

# =============================================================================
# Account queries & mutations
# =============================================================================

# Custom query with payment/credit fields not available in the library.
# Confirmed valid fields: minimumPayment, apr, interestRate, limit.
# Fields that do NOT exist: creditLimit, availableCredit, paymentDueDate, pastDueAmount.
GET_ACCOUNTS_WITH_PAYMENT_FIELDS_QUERY = """
query GetAccountsWithPaymentFields {
  accounts {
    id
    displayName
    syncDisabled
    deactivatedAt
    isHidden
    isAsset
    mask
    createdAt
    updatedAt
    displayLastUpdatedAt
    currentBalance
    displayBalance
    includeInNetWorth
    hideFromList
    hideTransactionsFromReports
    dataProvider
    dataProviderAccountId
    isManual
    transactionsCount
    holdingsCount
    order
    logoUrl
    type {
      name
      display
      group
      __typename
    }
    subtype {
      name
      display
      __typename
    }
    credential {
      id
      updateRequired
      disconnectedFromDataProviderAt
      dataProvider
      institution {
        id
        name
        status
        __typename
      }
      __typename
    }
    institution {
      id
      name
      primaryColor
      url
      __typename
    }
    minimumPayment
    interestRate
    apr
    limit
    __typename
  }
}
"""

# Extends the library's Common_UpdateAccount with payment fields
# (minimumPayment, interestRate, apr) -- confirmed writable via live API.
UPDATE_ACCOUNT_WITH_PAYMENT_FIELDS_MUTATION = """
mutation Common_UpdateAccount($input: UpdateAccountMutationInput!) {
    updateAccount(input: $input) {
        account {
            id
            displayName
            currentBalance
            displayBalance
            includeInNetWorth
            hideFromList
            hideTransactionsFromReports
            isManual
            isAsset
            type {
                name
                display
                group
                __typename
            }
            subtype {
                name
                display
                __typename
            }
            minimumPayment
            interestRate
            apr
            limit
            __typename
        }
        errors {
            fieldErrors {
                field
                messages
                __typename
            }
            message
            code
            __typename
        }
        __typename
    }
}
"""

# =============================================================================
# Recurring transaction queries
# =============================================================================

# Enriched recurring items query -- extends the library's
# Web_GetUpcomingRecurringTransactionItems with additional stream fields:
#   isActive, name, logoUrl, baseDate, reviewStatus, recurringType
# and item-level fields: isLate, isCompleted, markedPaidAt.
GET_RECURRING_TRANSACTIONS_ENRICHED_QUERY = """
query Web_GetUpcomingRecurringTransactionItems(
    $startDate: Date!, $endDate: Date!, $filters: RecurringTransactionFilter
) {
    recurringTransactionItems(
        startDate: $startDate
        endDate: $endDate
        filters: $filters
    ) {
        stream {
            id
            frequency
            amount
            isApproximate
            isActive
            name
            logoUrl
            baseDate
            reviewStatus
            recurringType
            merchant {
                id
                name
                logoUrl
                __typename
            }
            __typename
        }
        date
        isPast
        transactionId
        amount
        amountDiff
        isLate
        isCompleted
        markedPaidAt
        category {
            id
            name
            __typename
        }
        account {
            id
            displayName
            logoUrl
            __typename
        }
        __typename
    }
}
"""

# =============================================================================
# Merchant queries & mutations (recurring management)
# =============================================================================

# Query for merchant details including recurring stream.
GET_MERCHANT_DETAILS_QUERY = """
query Common_GetEditMerchant($merchantId: ID!) {
    merchant(id: $merchantId) {
        id
        name
        logoUrl
        transactionCount
        ruleCount
        canBeDeleted
        hasActiveRecurringStreams
        recurringTransactionStream {
            id
            frequency
            amount
            baseDate
            isActive
            __typename
        }
        __typename
    }
}
"""

# Mutation for updating merchant (including recurrence settings).
UPDATE_MERCHANT_MUTATION = """
mutation Common_UpdateMerchant($input: UpdateMerchantInput!) {
    updateMerchant(input: $input) {
        merchant {
            id
            name
            recurringTransactionStream {
                id
                frequency
                amount
                baseDate
                isActive
                __typename
            }
            __typename
        }
        errors {
            fieldErrors {
                field
                messages
                __typename
            }
            message
            code
            __typename
        }
        __typename
    }
}
"""

# =============================================================================
# Transaction rule queries & mutations (reverse-engineered from Monarch web app)
# =============================================================================

GET_TRANSACTION_RULES_QUERY = """
query GetTransactionRules {
  transactionRules {
    id
    order
    merchantCriteriaUseOriginalStatement
    merchantCriteria {
      operator
      value
      __typename
    }
    originalStatementCriteria {
      operator
      value
      __typename
    }
    merchantNameCriteria {
      operator
      value
      __typename
    }
    amountCriteria {
      operator
      isExpense
      value
      valueRange {
        lower
        upper
        __typename
      }
      __typename
    }
    categoryIds
    accountIds
    categories {
      id
      name
      icon
      __typename
    }
    accounts {
      id
      displayName
      __typename
    }
    setMerchantAction {
      id
      name
      __typename
    }
    setCategoryAction {
      id
      name
      icon
      __typename
    }
    addTagsAction {
      id
      name
      color
      __typename
    }
    linkGoalAction {
      id
      name
      __typename
    }
    setHideFromReportsAction
    reviewStatusAction
    recentApplicationCount
    lastAppliedAt
    __typename
  }
}
"""

CREATE_TRANSACTION_RULE_MUTATION = """
mutation Common_CreateTransactionRuleMutationV2($input: CreateTransactionRuleInput!) {
  createTransactionRuleV2(input: $input) {
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""

UPDATE_TRANSACTION_RULE_MUTATION = """
mutation Common_UpdateTransactionRuleMutationV2($input: UpdateTransactionRuleInput!) {
  updateTransactionRuleV2(input: $input) {
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""

DELETE_TRANSACTION_RULE_MUTATION = """
mutation Common_DeleteTransactionRule($id: ID!) {
  deleteTransactionRule(id: $id) {
    deleted
    errors {
      fieldErrors {
        field
        messages
        __typename
      }
      message
      code
      __typename
    }
    __typename
  }
}
"""
